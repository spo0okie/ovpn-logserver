<?php

namespace openvpnlogserver\arms;

use app\components\integrations\IntegrationProvider;
use app\models\base\ArmsModel;
use app\models\NetIps;
use Yii;
use yii\helpers\Html;

/**
 * Интеграция инвентаризации ARMS с OpenVPN LogServer (только чтение).
 *
 * Поставляется вместе с логсервером (integrations/arms/), в ARMS не входит:
 * инстанс, у которого логсервера нет, о провайдере ничего не знает. Контракт
 * провайдера — docs/dev/integrations.md в репозитории ARMS.
 *
 * Привязка — по имени IP-записи. Provision логсервера заводит VPN-адрес
 * клиента в инвентаризации под именем `<префикс><CN>` (`ovpn-ivanov`,
 * `ovpn2fa-ivanov`), и префикс однозначно называет инстанс OpenVPN. Поэтому
 * отдельно помечать VPN-сети не нужно: провайдер применим к IP, чьё имя
 * начинается с известного префикса.
 *
 * Что даёт (статус пары «CN + инстанс»: online → enabled → disabled →
 * revoked → not found, docs/api.md логсервера):
 * - иконка статуса у IP везде, где адрес рисуется (карточки ОС, сотрудника,
 *   оборудования); у online — время сессии, тикающее на странице;
 * - колонки «Статус OpenVPN» и «Источник» в списке IP и в таблице адресов
 *   карточки сети: у online — текущий адрес подключения, у остальных —
 *   последнее подключение, приглушённо;
 * - панель в карточке IP: статус, источник, сертификаты, ссылка в веб-
 *   интерфейс логсервера.
 *
 * Все виды — один батч-запрос POST /api/v1/integrations/status на страницу.
 *
 * Конфиг (params-local.php ARMS):
 * ```php
 * require_once '/opt/openvpn-logserver/integrations/arms/autoload.php';
 * return [
 *     'integrations' => [
 *         'openvpn' => [
 *             'class' => \openvpnlogserver\arms\OpenVpnProvider::class,
 *             'url' => 'https://vpnlog.local',  //адрес логсервера, достижимый С СЕРВЕРА ARMS
 *             'user' => '...',                  //учётка логсервера (config/auth.yaml)
 *             'password' => '...',
 *             //префикс имени IP-записи => имя инстанса (openvpn.server_name
 *             //логсервера); null - любой инстанс. По умолчанию - соглашение
 *             //provision для одиночного инстанса:
 *             //'prefixes' => ['ovpn-' => 'local', 'ovpn2fa-' => 'local-2fa'],
 *             //'web' => 'https://vpnlog.corp',  //адрес для браузера, если отличается от url
 *             //'title' => 'OpenVPN',
 *             //'expiringDays' => 30,            //предупреждать о сертификате, истекающем раньше
 *             //'cacheTtl' => 0,                 //панель: 0 - обновлять при каждом открытии
 *             //'cellTtl' => 30,                 //колонки и иконки (не меньше 15)
 *             //'timeout' => 5,
 *             //'verifySsl' => true,
 *         ],
 *     ],
 * ];
 * ```
 */
class OpenVpnProvider extends IntegrationProvider
{
	const PANEL = 'status';
	const COLUMN_STATUS = 'status';
	const COLUMN_SOURCE = 'source';
	const BADGE = 'badge';

	const DEFAULT_PREFIXES = ['ovpn-' => 'local', 'ovpn2fa-' => 'local-2fa'];

	/**
	 * Вид статусов: [цвет bootstrap, текст, пояснение]. Порядок = приоритет
	 * (так их считает логсервер).
	 */
	const STATES = [
		'online'    => ['success',   'в сети',    'клиент подключён'],
		'enabled'   => ['primary',   'включён',   'сертификат действует, CCD на инстансе есть — может подключиться'],
		'disabled'  => ['secondary', 'выключен',  'сертификат действует, но CCD на инстансе нет — подключиться не может'],
		'revoked'   => ['danger',    'отозван',   'действующих сертификатов нет'],
		'not_found' => ['light',     'нет в VPN', 'сертификатов с таким CN в OpenVPN LogServer нет'],
	];

	public function getTitle(): string
	{
		return $this->config['title'] ?? 'OpenVPN';
	}

	public function isConfigured(): bool
	{
		return !empty($this->config['url'])
			&& !empty($this->config['user'])
			&& isset($this->config['password']);
	}

	public function appliesTo(ArmsModel $model): bool
	{
		return $model instanceof NetIps && !is_null($this->binding($model));
	}

	/**
	 * Привязка «инстанс|CN» из имени IP-записи.
	 * Длинный префикс проверяется первым: при префиксах `ovpn-` и
	 * `ovpn-2fa-` запись `ovpn-2fa-ivanov` относится ко второму.
	 */
	public function binding(ArmsModel $model): ?string
	{
		$pair = $this->parseName((string)($model->name ?? ''));
		return $pair ? $pair['server'].'|'.$pair['cn'] : null;
	}

	/**
	 * Имя IP-записи -> ['cn' =>, 'server' =>] или null (не VPN-адрес)
	 */
	public function parseName(string $name): ?array
	{
		$name = trim($name);
		$prefixes = $this->prefixes();
		uksort($prefixes, static fn($a, $b) => strlen($b) <=> strlen($a));
		foreach ($prefixes as $prefix => $server) {
			if ($prefix === '' || strncmp($name, $prefix, strlen($prefix)) !== 0) continue;
			$cn = substr($name, strlen($prefix));
			if ($cn === '') return null;
			return ['cn' => $cn, 'server' => (string)$server];
		}
		return null;
	}

	public function prefixes(): array
	{
		return $this->config['prefixes'] ?? static::DEFAULT_PREFIXES;
	}

	/** Привязка -> ['cn' =>, 'server' => string|null] */
	protected function pair(string $binding): array
	{
		[$server, $cn] = explode('|', $binding, 2);
		return ['cn' => $cn, 'server' => $server === '' ? null : $server];
	}

	public function panels(ArmsModel $model): array
	{
		return [
			static::PANEL => [
				'title' => $this->getTitle(),
				//логсервер локальный и дешёвый, а «в сети» устаревать не должно
				'ttl' => $this->config['cacheTtl'] ?? 0,
			],
		];
	}

	public function renderPanel(string $panelId, ArmsModel $model): string
	{
		$pair = $this->pair($this->binding($model));
		$item = $this->fetchStatuses([$pair])[0] ?? null;
		if (!$item) throw new \RuntimeException('OpenVPN LogServer не вернул статус');

		return $this->renderView('panel', [
			'item' => $item,
			'pair' => $pair,
			'provider' => $this,
		]);
	}

	public function gridColumns(string $modelClass): array
	{
		if (!is_a($modelClass, NetIps::class, true)) return [];
		return [
			static::COLUMN_STATUS => [
				'title' => 'Статус OpenVPN',
				'hint' => 'Статус VPN-клиента по данным OpenVPN LogServer: в сети / включён / выключен / отозван / нет в VPN',
			],
			static::COLUMN_SOURCE => [
				'title' => 'Источник',
				'hint' => 'Откуда подключён клиент (адрес и геометка); приглушённо — последнее подключение, если сейчас не в сети',
			],
		];
	}

	public function itemBadges(string $modelClass): array
	{
		if (!is_a($modelClass, NetIps::class, true)) return [];
		return [static::BADGE => ['title' => 'Статус OpenVPN']];
	}

	/**
	 * Колонки и иконки: один POST на весь набор (пары дедуплицируются —
	 * несколько IP-записей одного клиента на странице стоят одну пару)
	 */
	public function renderCells(string $columnId, array $models): array
	{
		$pairs = [];
		foreach ($models as $model) {
			$binding = $this->binding($model);
			if (!is_null($binding)) $pairs[$binding] = $this->pair($binding);
		}
		if (!$pairs) return [];

		$statuses = array_combine(array_keys($pairs), $this->fetchStatuses(array_values($pairs)));

		$cells = [];
		foreach ($models as $model) {
			$item = $statuses[$this->binding($model)] ?? null;
			if (!$item) continue;
			switch ($columnId) {
				case static::COLUMN_STATUS: $cells[$model->id] = $this->renderStatus($item); break;
				case static::COLUMN_SOURCE: $cells[$model->id] = $this->renderSource($item); break;
				case static::BADGE:         $cells[$model->id] = $this->renderBadge($item); break;
			}
		}
		return $cells;
	}

	/** Вид статуса: [цвет, текст, пояснение] с уточнением «отозван/истёк» */
	public function stateView(array $item): array
	{
		$view = static::STATES[$item['state']] ?? ['secondary', $item['state'], ''];
		if ($item['state'] === 'revoked' && !($item['certificates']['revoked'] ?? 0)) {
			$view = ['danger', 'истёк', 'сертификат истёк, действующих нет'];
		}
		return $view;
	}

	/**
	 * Иконка статуса у IP. Кружок цвета статуса, у online — ещё и время
	 * сессии. Подробности — в подсказке и в карточке IP (клик по адресу).
	 */
	public function renderBadge(array $item): string
	{
		[$color, $text, $hint] = $this->stateView($item);
		$icon = $item['state'] === 'not_found' ? 'far fa-circle text-secondary' : 'fas fa-circle text-'.$color;
		$html = '<i class="'.$icon.'" style="font-size:.6em;vertical-align:middle"></i>';
		if ($item['state'] === 'online') {
			$html .= ' <small>'.$this->renderElapsed($item['active_session']['connected_at']).'</small>';
		}
		$title = $this->getTitle().': '.$text.' — '.$hint;
		$source = $this->sourceText($item);
		if ($source) $title .= "\n".($item['state'] === 'online' ? 'Подключён: ' : 'Последнее подключение: ').$source;
		return Html::tag('span', $html, ['class' => 'text-nowrap', 'title' => $title]);
	}

	/** Колонка «Статус OpenVPN»: бейдж, у online — тикающее время сессии */
	public function renderStatus(array $item): string
	{
		[$color, $text, $hint] = $this->stateView($item);
		$class = $item['state'] === 'not_found' ? 'badge bg-light text-secondary border' : 'badge bg-'.$color;
		$html = Html::tag('span', Html::encode($text), ['class' => $class, 'title' => $hint]);
		if ($item['state'] === 'online') {
			$html .= ' '.$this->renderElapsed($item['active_session']['connected_at']);
		}
		return Html::tag('span', $html, ['class' => 'text-nowrap']);
	}

	/**
	 * Колонка «Источник»: у online — текущее подключение, иначе последнее
	 * (приглушённо и с датой — чтобы история не читалась как «сейчас»)
	 */
	public function renderSource(array $item): string
	{
		$source = $this->sourceText($item);
		if (!$source) return '<span class="text-secondary opacity-75">&mdash;</span>';
		if ($item['state'] === 'online') return Html::encode($source);
		return Html::tag('span', Html::encode($source), [
			'class' => 'text-secondary opacity-75',
			'title' => 'Последнее подключение; сейчас не в сети',
		]);
	}

	/** «адрес · страна, город [· когда]» по текущей либо последней сессии */
	public function sourceText(array $item): ?string
	{
		$online = $item['state'] === 'online';
		$session = $online ? ($item['active_session'] ?? null) : ($item['last_session'] ?? null);
		if (!$session) return null;
		$parts = [$session['source_ip']];
		$geo = implode(', ', array_filter([$session['country'] ?? null, $session['city'] ?? null]));
		if ($geo !== '') $parts[] = $geo;
		if (!$online) $parts[] = Yii::$app->formatter->asDatetime(static::timestamp($session['connected_at']));
		return implode(' · ', $parts);
	}

	/**
	 * Время сессии: начальный текст рендерится здесь, дальше его ведёт
	 * скрипт ядра по data-integration-elapsed (кэш ячеек общий, поэтому
	 * в HTML — момент начала, а не «сколько прошло»)
	 */
	public function renderElapsed(string $since): string
	{
		$ts = static::timestamp($since);
		return Html::tag('span', Html::encode(static::formatElapsed(time() - $ts)), [
			'data-integration-elapsed' => $ts,
			'title' => 'Сессия с '.Yii::$app->formatter->asDatetime($ts),
		]);
	}

	/** Длительность так же, как её показывает скрипт ядра */
	public static function formatElapsed(int $seconds): string
	{
		$seconds = max(0, $seconds);
		$d = intdiv($seconds, 86400);
		$h = intdiv($seconds % 86400, 3600);
		$m = intdiv($seconds % 3600, 60);
		$s = $seconds % 60;
		if ($d) return $d.'д '.$h.'ч';
		if ($h) return $h.'ч '.sprintf('%02d', $m).'м';
		return $m.'м '.sprintf('%02d', $s).'с';
	}

	/** Время логсервера (naive UTC, ISO) -> unix timestamp */
	public static function timestamp(string $value): int
	{
		return (new \DateTime($value, new \DateTimeZone('UTC')))->getTimestamp();
	}

	/**
	 * Рендер view провайдера. Базовый класс ищет view в дереве ARMS, а наши
	 * лежат рядом с провайдером — поэтому свой путь, и id провайдера на него
	 * не влияет. $compact приходит во view, как у встроенных провайдеров.
	 */
	public function renderView(string $view, array $params = []): string
	{
		return Yii::$app->view->renderFile(
			dirname(__DIR__).'/views/'.$view.'.php',
			array_merge(['compact' => $this->compact], $params)
		);
	}

	/** URL веб-интерфейса логсервера для браузера (L0-ссылки) */
	public function webUrl(string $path): string
	{
		return rtrim($this->config['web'] ?? $this->config['url'], '/').$path;
	}

	/**
	 * Батч-статус пар (POST /api/v1/integrations/status).
	 * @param array $pairs [['cn' =>, 'server' =>], ...]
	 * @return array элементы ответа в порядке $pairs
	 * @throws \RuntimeException транспорт/авторизация/формат (ловит ядро)
	 */
	protected function fetchStatuses(array $pairs): array
	{
		$data = $this->apiPost('/api/v1/integrations/status', ['items' => array_values($pairs)]);
		$items = $data['data'] ?? null;
		if (!is_array($items) || count($items) !== count($pairs)) {
			throw new \RuntimeException('Некорректный ответ OpenVPN LogServer: число статусов не совпадает с запросом');
		}
		return $items;
	}

	/**
	 * POST JSON к API логсервера.
	 * @throws \RuntimeException
	 */
	protected function apiPost(string $path, array $payload): array
	{
		[$body, $status] = $this->httpPost(rtrim($this->config['url'], '/').$path, json_encode($payload));

		if ($status === 401) {
			throw new \RuntimeException('OpenVPN LogServer: неверные учётные данные (user/password в конфиге интеграции)');
		}
		$data = json_decode($body, true);
		if ($status !== 200 || !is_array($data)) {
			$snippet = trim(mb_substr(preg_replace('/\s+/', ' ', strip_tags($body)), 0, 160));
			throw new \RuntimeException("Некорректный ответ OpenVPN LogServer (HTTP $status): "
				.($snippet ?: 'пустой ответ'));
		}
		return $data;
	}

	/**
	 * HTTP POST с Basic Auth. Вынесен отдельным методом: тесты подменяют
	 * его, не трогая сеть.
	 * @return array [string тело, int HTTP-код (0 если не распознан)]
	 * @throws \RuntimeException при ошибке транспорта
	 */
	protected function httpPost(string $url, string $json): array
	{
		$verify = (bool)($this->config['verifySsl'] ?? true);
		$context = stream_context_create([
			'http' => [
				'method' => 'POST',
				'timeout' => $this->timeout(),
				'ignore_errors' => true, //тело нужно и при 4xx
				'header' => "Content-Type: application/json\r\n"
					."Accept: application/json\r\n"
					.'Authorization: Basic '
					.base64_encode($this->config['user'].':'.$this->config['password'])."\r\n",
				'content' => $json,
			],
			'ssl' => [
				'verify_peer' => $verify,
				'verify_peer_name' => $verify,
			],
		]);

		$response = @file_get_contents($url, false, $context);
		if ($response === false) throw new \RuntimeException('OpenVPN LogServer недоступен');

		$status = 0;
		if (isset($http_response_header[0]) && preg_match('#^HTTP/\S+\s+(\d+)#', $http_response_header[0], $m)) {
			$status = (int)$m[1];
		}
		return [$response, $status];
	}
}
