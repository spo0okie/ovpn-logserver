# Wrapper-скрипты для OpenVPN

Эта директория содержит wrapper-скрипты для интеграции с OpenVPN.

## Проблема

Оригинальные скрипты `client_connect.py` и `client_disconnect.py` используют относительные импорты модуля `core`:

```python
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

При копировании скриптов в `/etc/openvpn/scripts/` этот путь указывает на `/etc/openvpn`, а не на `/opt/openvpn-logserver`, что приводит к ошибке:

```
ModuleNotFoundError: No module named 'core'
```

## Решение

Wrapper-скрипты устанавливают абсолютный путь к проекту перед импортом модулей:

```python
sys.path.insert(0, '/opt/openvpn-logserver')
from collector.client_connect import main
```

## Установка

### Вариант 1: Копирование wrapper-скриптов (рекомендуется)

```bash
# Создаем директорию для скриптов
mkdir -p /etc/openvpn/scripts

# Копируем wrapper-скрипты
cp collector/openvpn_scripts/client-connect /etc/openvpn/scripts/
cp collector/openvpn_scripts/client-disconnect /etc/openvpn/scripts/

# Устанавливаем права на выполнение
chmod +x /etc/openvpn/scripts/client-connect
chmod +x /etc/openvpn/scripts/client-disconnect
```

### Вариант 2: Создание через heredoc

```bash
mkdir -p /etc/openvpn/scripts

cat > /etc/openvpn/scripts/client-connect <<'EOF'
#!/usr/bin/env python3
import sys
sys.path.insert(0, '/opt/openvpn-logserver')
from collector.client_connect import main
if __name__ == '__main__':
    sys.exit(main())
EOF

cat > /etc/openvpn/scripts/client-disconnect <<'EOF'
#!/usr/bin/env python3
import sys
sys.path.insert(0, '/opt/openvpn-logserver')
from collector.client_disconnect import main
if __name__ == '__main__':
    sys.exit(main())
EOF

chmod +x /etc/openvpn/scripts/client-connect
chmod +x /etc/openvpn/scripts/client-disconnect
```

## Настройка OpenVPN

Добавьте в `/etc/openvpn/server.conf`:

```conf
# Скрипты подключения/отключения
client-connect /etc/openvpn/scripts/client-connect
client-disconnect /etc/openvpn/scripts/client-disconnect

# Переменные окружения для скриптов
setenv-safe common_name
setenv-safe trusted_ip
setenv-safe trusted_port
setenv-safe ifconfig_pool_remote_ip
setenv-safe bytes_sent
setenv-safe bytes_received
setenv-safe time_duration
```

## Нестандартный путь установки

Если проект установлен не в `/opt/openvpn-logserver`, задайте переменную окружения:

```bash
export OPENVPN_LOGSERVER_PATH=/path/to/project
```

Или отредактируйте wrapper-скрипты, изменив значение `PROJECT_PATH`.
