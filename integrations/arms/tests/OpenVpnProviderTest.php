<?php

namespace tests\unit\external;

use app\models\NetIps;
use app\models\Users;
use Codeception\Test\Unit;
use openvpnlogserver\arms\OpenVpnProvider;

//провайдер поставляется с логсервером: тест копируется в дерево ARMS
//(integrations/arms/README.md, «Тесты»), а автозагрузчик берётся по
//LOGSERVER_ARMS_DIR либо из соседнего каталога, если тест не копировали
require_once (getenv('LOGSERVER_ARMS_DIR') ?: dirname(__DIR__)).'/autoload.php';

/**
 * Тесты провайдера OpenVPN LogServer: привязка по имени IP-записи, батч
 * статусов на страницу, рендер иконки/колонок/панели. Транспорт (httpPost)
 * подменён в наследнике — сеть не используется.
 */
class OpenVpnProviderTest extends Unit
{
	/**
	 * @var \UnitTester
	 */
	protected $tester;

	/**
	 * Провайдер с подменённым транспортом
	 * @param callable|null $responder fn(array $payload): [string тело, int код];
	 *   по умолчанию отвечает статусами из $statuses по CN
	 */
	private function makeProvider(array $statuses = [], array $config = [], ?callable $responder = null): OpenVpnProvider
	{
		$provider = new class extends OpenVpnProvider {
			public array $requests = [];
			public $responder;

			protected function httpPost(string $url, string $json): array
			{
				$payload = json_decode($json, true);
				$this->requests[] = ['url' => $url, 'payload' => $payload];
				return ($this->responder)($payload);
			}
		};
		$provider->id = 'openvpn';
		$provider->config = array_merge([
			'url' => 'http://logserver:8000/',
			'user' => 'arms',
			'password' => 'secret',
			'web' => 'https://vpnlog.corp',
		], $config);
		$provider->responder = $responder ?? static function (array $payload) use ($statuses) {
			$data = [];
			foreach ($payload['items'] as $item) {
				$data[] = array_merge(
					['cn' => $item['cn'], 'server' => $item['server'], 'state' => 'not_found',
						'has_ccd' => false, 'certificates' => null,
						'active_session' => null, 'last_session' => null],
					$statuses[$item['cn']] ?? []
				);
			}
			return [json_encode(['data' => $data]), 200];
		};
		return $provider;
	}

	private function makeIp(int $id, ?string $name): NetIps
	{
		$ip = new NetIps();
		$ip->id = $id;
		$ip->name = $name;
		return $ip;
	}

	private static function session(string $connectedAt, string $ip = '203.0.113.5'): array
	{
		return ['id' => 1, 'server_name' => 'local', 'status' => 'active',
			'connected_at' => $connectedAt, 'disconnected_at' => null,
			'source_ip' => $ip, 'virtual_ip' => '10.8.0.10',
			'country' => 'Russia', 'city' => 'Chelyabinsk'];
	}

	private static function certs(int $active = 1, int $revoked = 0, int $expired = 0): array
	{
		return ['total' => $active + $revoked + $expired, 'active' => $active,
			'revoked' => $revoked, 'expired' => $expired,
			'valid_to' => $active ? '2030-01-01T00:00:00' : null];
	}

	/** Привязка из имени: префикс -> инстанс, длинный префикс первым */
	public function testBinding()
	{
		$provider = $this->makeProvider();
		$this->assertSame('local|ivanov', $provider->binding($this->makeIp(1, 'ovpn-ivanov')));
		$this->assertSame('local-2fa|ivanov', $provider->binding($this->makeIp(2, 'ovpn2fa-ivanov')));
		$this->assertNull($provider->binding($this->makeIp(3, 'srv-dc01')), 'не VPN-адрес');
		$this->assertNull($provider->binding($this->makeIp(4, 'ovpn-')), 'пустой CN');
		$this->assertNull($provider->binding($this->makeIp(5, null)));

		$provider = $this->makeProvider([], ['prefixes' => ['vpn-' => 'msk', 'vpn-2fa-' => 'msk-2fa', 'any-' => null]]);
		$this->assertSame('msk-2fa|petrov', $provider->binding($this->makeIp(6, 'vpn-2fa-petrov')));
		$this->assertSame('msk|petrov', $provider->binding($this->makeIp(7, 'vpn-petrov')));
		$this->assertSame('|petrov', $provider->binding($this->makeIp(8, 'any-petrov')), 'любой инстанс');
	}

	public function testAppliesTo()
	{
		$provider = $this->makeProvider();
		$this->assertTrue($provider->appliesTo($this->makeIp(1, 'ovpn-ivanov')));
		$this->assertFalse($provider->appliesTo($this->makeIp(2, 'printer')));
		$this->assertFalse($provider->appliesTo(new Users()));
		$this->assertSame([], $provider->gridColumns(Users::class));
		$this->assertSame(['status', 'source'], array_keys($provider->gridColumns(NetIps::class)));
		$this->assertSame(['badge'], array_keys($provider->itemBadges(NetIps::class)));
	}

	/** Страница — один запрос; пары уникальны, server null уходит как null */
	public function testCellsBatch()
	{
		$now = gmdate('Y-m-d\TH:i:s', time() - 3700);
		$provider = $this->makeProvider([
			'ivanov' => ['state' => 'online', 'certificates' => self::certs(),
				'active_session' => self::session($now)],
			'petrov' => ['state' => 'disabled', 'certificates' => self::certs(),
				'last_session' => self::session('2026-09-01T10:00:00', '198.51.100.7')],
		], ['prefixes' => ['ovpn-' => 'local', 'any-' => null]]);

		$ips = [
			$this->makeIp(1, 'ovpn-ivanov'),
			$this->makeIp(2, 'ovpn-petrov'),
			$this->makeIp(3, 'ovpn-ivanov'), //тот же клиент - та же пара
			$this->makeIp(4, 'any-ghost'),
		];

		$status = $provider->renderCells('status', $ips);
		$this->assertCount(1, $provider->requests, 'один запрос на страницу');
		$this->assertSame('http://logserver:8000/api/v1/integrations/status', $provider->requests[0]['url']);
		$this->assertSame([
			['cn' => 'ivanov', 'server' => 'local'],
			['cn' => 'petrov', 'server' => 'local'],
			['cn' => 'ghost', 'server' => null],
		], $provider->requests[0]['payload']['items']);

		$this->assertStringContainsString('в сети', $status[1]);
		$this->assertStringContainsString('data-integration-elapsed', $status[1]);
		$this->assertSame($status[1], $status[3]);
		$this->assertStringContainsString('выключен', $status[2]);
		$this->assertStringContainsString('нет в VPN', $status[4]);

		$source = $provider->renderCells('source', $ips);
		$this->assertStringContainsString('203.0.113.5 · Russia, Chelyabinsk', $source[1]);
		$this->assertStringNotContainsString('opacity', $source[1], 'онлайн — не приглушён');
		$this->assertStringContainsString('198.51.100.7', $source[2]);
		$this->assertStringContainsString('opacity-75', $source[2], 'история — приглушённо');
		$this->assertStringContainsString('&mdash;', $source[4]);

		$badge = $provider->renderCells('badge', $ips);
		$this->assertStringContainsString('text-success', $badge[1]);
		$this->assertStringContainsString('data-integration-elapsed', $badge[1]);
		$this->assertStringContainsString('text-secondary', $badge[2]);
		$this->assertStringNotContainsString('data-integration-elapsed', $badge[2]);
	}

	/** Отозван vs истёк: статус один (revoked), подпись различается */
	public function testRevokedLabel()
	{
		$provider = $this->makeProvider([
			'a' => ['state' => 'revoked', 'certificates' => self::certs(0, 1, 0)],
			'b' => ['state' => 'revoked', 'certificates' => self::certs(0, 0, 2)],
		]);
		$cells = $provider->renderCells('status', [$this->makeIp(1, 'ovpn-a'), $this->makeIp(2, 'ovpn-b')]);
		$this->assertStringContainsString('отозван', $cells[1]);
		$this->assertStringContainsString('истёк', $cells[2]);
	}

	public function testPanel()
	{
		$provider = $this->makeProvider([
			'ivanov' => ['state' => 'enabled', 'has_ccd' => true, 'certificates' => self::certs(1, 1),
				'last_session' => self::session('2026-09-01T10:00:00')],
		]);
		$html = $provider->renderPanel('status', $this->makeIp(1, 'ovpn-ivanov'));
		$this->assertStringContainsString('включён', $html);
		$this->assertStringContainsString('Последнее подключение', $html);
		$this->assertStringContainsString('https://vpnlog.corp/accounts/ivanov', $html);
		$this->assertStringContainsString('local', $html);

		$html = $this->makeProvider()->renderPanel('status', $this->makeIp(2, 'ovpn-ghost'));
		$this->assertStringContainsString('нет в VPN', $html);
		$this->assertStringNotContainsString('/accounts/', $html, 'ссылки на несуществующий аккаунт нет');
	}

	public function testErrors()
	{
		$provider = $this->makeProvider([], [], static fn() => ['{"detail":"Authentication required"}', 401]);
		try {
			$provider->renderCells('status', [$this->makeIp(1, 'ovpn-x')]);
			$this->fail('401 должен давать исключение');
		} catch (\RuntimeException $e) {
			$this->assertStringContainsString('учётные данные', $e->getMessage());
		}

		$provider = $this->makeProvider([], [], static fn() => ['{"data":[]}', 200]);
		$this->expectException(\RuntimeException::class);
		$provider->renderCells('status', [$this->makeIp(1, 'ovpn-x')]);
	}

	public function testFormatElapsed()
	{
		$this->assertSame('0м 07с', OpenVpnProvider::formatElapsed(7));
		$this->assertSame('2ч 05м', OpenVpnProvider::formatElapsed(2 * 3600 + 5 * 60 + 9));
		$this->assertSame('3д 4ч', OpenVpnProvider::formatElapsed(3 * 86400 + 4 * 3600));
		$this->assertSame(0, OpenVpnProvider::timestamp('1970-01-01T00:00:00'), 'время логсервера — UTC');
	}
}
