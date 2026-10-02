<?php
/**
 * Панель «OpenVPN» в карточке IP-адреса: статус и источник — как в колонках
 * списка, плюс инстанс, срок сертификата и ссылка в веб-интерфейс
 * логсервера. Кэш панелей общий на инстанс ARMS: HTML одинаков для всех
 * зрителей, время сессии ведёт скрипт ядра по data-integration-elapsed.
 */

use openvpnlogserver\arms\OpenVpnProvider;
use yii\helpers\Html;

/* @var $item array элемент ответа POST /api/v1/integrations/status */
/* @var $pair array ['cn' =>, 'server' => string|null] */
/* @var $provider OpenVpnProvider */
/* @var $compact bool */

$formatter = Yii::$app->formatter;
$found = $item['state'] !== 'not_found';
$online = $item['state'] === 'online';
$source = $provider->sourceText($item);

if ($compact) {
	echo $provider->renderStatus($item);
	return;
}
?>
<div class="mb-1">
	<?= $provider->renderStatus($item) ?>
	<span class="text-secondary ms-1">
		CN <strong><?= Html::encode($pair['cn']) ?></strong><?= $pair['server'] !== null
			? ', инстанс <strong>'.Html::encode($pair['server']).'</strong>' : '' ?>
	</span>
</div>

<?php if ($source) { ?>
	<div class="<?= $online ? '' : 'text-secondary opacity-75' ?>">
		<?= $online ? 'Подключён из' : 'Последнее подключение' ?>: <?= Html::encode($source) ?>
		<?php if ($online && !empty($item['active_session']['virtual_ip'])) { ?>
			<span class="text-secondary">(VPN-адрес <?= Html::encode($item['active_session']['virtual_ip']) ?>)</span>
		<?php } ?>
	</div>
<?php } elseif ($found) { ?>
	<div class="text-secondary opacity-75">На этом инстансе не подключался</div>
<?php } ?>

<?php if ($found) {
	$certs = $item['certificates'];
	$lines = [];
	if ($certs['active']) {
		$validTo = $certs['valid_to'] ? OpenVpnProvider::timestamp($certs['valid_to']) : null;
		$text = 'Сертификат действует'.($validTo ? ' до '.$formatter->asDate($validTo) : '');
		$expiringDays = (int)($provider->config['expiringDays'] ?? 30);
		$lines[] = ($validTo && $validTo - time() < $expiringDays * 86400)
			? '<span class="text-warning-emphasis">'.Html::encode($text.' — скоро истечёт').'</span>'
			: Html::encode($text);
	}
	$history = array_filter([
		$certs['revoked'] ? 'отозванных: '.$certs['revoked'] : null,
		$certs['expired'] ? 'истёкших: '.$certs['expired'] : null,
	]);
	if ($history) $lines[] = '<span class="text-secondary">'.Html::encode(implode(', ', $history)).'</span>';
	if ($certs['active'] && !$item['has_ccd']) {
		$lines[] = '<span class="text-secondary">CCD на инстансе нет — подключиться не может</span>';
	}
	if ($lines) echo '<div class="small">'.implode('<br>', $lines).'</div>';
} ?>

<?php if ($found) { ?>
	<div class="mt-1">
		<?= Html::a('<i class="fas fa-external-link-alt"></i> Открыть в OpenVPN LogServer',
			$provider->webUrl('/accounts/'.rawurlencode($pair['cn'])),
			['target' => '_blank', 'rel' => 'noopener']) ?>
	</div>
<?php } ?>
