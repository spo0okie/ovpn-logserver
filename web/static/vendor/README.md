# Локальные зависимости веб-интерфейса

Все CSS, JavaScript и шрифты интерфейса поставляются с проектом и доступны
через `/static/vendor/`. Браузеру достаточно доступа к LogServer по локальной
сети; подключения к CDN не используются, в том числе на странице входа.

| npm-пакет | Версия | Используемые файлы |
| --- | --- | --- |
| jquery | 3.7.0 | `dist/jquery.min.js` |
| bootstrap | 5.3.0 | `dist/css/bootstrap.min.css`, `dist/js/bootstrap.bundle.min.js` и их карты исходников |
| bootstrap-icons | 1.10.0 | `font/bootstrap-icons.css`, `font/fonts/*.woff*` |
| datatables.net | 1.13.6 | `js/jquery.dataTables.min.js` |
| datatables.net-bs5 | 1.13.6 | `css/dataTables.bootstrap5.min.css`, `js/dataTables.bootstrap5.min.js` |

Файлы скопированы без изменений из архивов npm Registry:
`https://registry.npmjs.org/<пакет>/-/<пакет>-<версия>.tgz`.
Лицензия каждого пакета находится в его каталоге. Bootstrap bundle уже включает
Popper; относительные пути к шрифтам Bootstrap Icons сохранены.

Для развёртывания необходимо переносить весь каталог `web/static` вместе
с шаблонами. Docker-образ уже включает его через `COPY web/ /app/web/`.
Загрузка зависимостей при запуске приложения не требуется.
