<?php
/**
 * Автозагрузка провайдера OpenVPN LogServer для инвентаризации ARMS.
 *
 * Провайдер поставляется вместе с логсервером, а не с ARMS: в дереве ARMS
 * его нет, composer ARMS о нём не знает. Инстанс ARMS подключает его сам —
 * одной строкой в начале config/params-local.php:
 *
 *     require_once '/opt/openvpn-logserver/integrations/arms/autoload.php';
 *
 * Регистрируется только загрузчик пространства имён openvpnlogserver\arms\;
 * сами классы (и базовый app\components\integrations\IntegrationProvider)
 * грузятся лениво — когда реестр интеграций ARMS проверит class_exists()
 * уже поднятого приложения. Поэтому require из params-local.php безопасен:
 * на этапе сборки конфига ни Yii-алиасов, ни классов ARMS не нужно.
 */

spl_autoload_register(static function (string $class): void {
	$prefix = 'openvpnlogserver\\arms\\';
	if (strncmp($class, $prefix, strlen($prefix)) !== 0) return;

	$file = __DIR__.'/src/'.str_replace('\\', '/', substr($class, strlen($prefix))).'.php';
	if (is_file($file)) require $file;
});
