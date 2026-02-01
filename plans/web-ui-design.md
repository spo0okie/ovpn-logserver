# Web UI Design

## Технологии

- **Backend:** FastAPI + Jinja2 Templates
- **Frontend:** Bootstrap 5 + vanilla JavaScript
- **Charts:** Chart.js для визуализации статистики
- **Tables:** DataTables для сортировки и фильтрации
- **Icons:** Bootstrap Icons

## Страницы

### 1. Dashboard (/)

Главная страница с обзором состояния системы.

**Layout:**
```
┌─────────────────────────────────────────────────────────────┐
│  Logo                    Dashboard    Accounts   Sessions   │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐           │
│  │ Active      │ │ Sessions    │ │ Failed      │           │
│  │ Sessions    │ │ Today       │ │ Attempts    │           │
│  │    15       │ │    45       │ │     3       │           │
│  └─────────────┘ └─────────────┘ └─────────────┘           │
│                                                             │
│  ┌─────────────────────────┐  ┌─────────────────────────┐  │
│  │  Active Sessions        │  │  Recent Failures        │  │
│  │  [Table]                │  │  [Table]                │  │
│  │  - user1 (RU/Moscow)    │  │  - user5: revoked       │  │
│  │  - user2 (DE/Berlin)    │  │  - user7: no CCD        │  │
│  └─────────────────────────┘  └─────────────────────────┘  │
│                                                             │
│  ┌─────────────────────────┐  ┌─────────────────────────┐  │
│  │  Connections (7 days)   │  │  Top Countries          │  │
│  │  [Line Chart]           │  │  [Pie Chart]            │  │
│  └─────────────────────────┘  └─────────────────────────┘  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**Компоненты:**
- Карточки с ключевыми метриками (active sessions, today's sessions, failed attempts)
- Таблица активных сессий (5 последних)
- Таблица недавних неудачных попыток (5 последних)
- График подключений за 7 дней
- Круговая диаграмма топ-5 стран

### 2. Accounts (/accounts)

Список всех аккаунтов.

**Layout:**
```
┌─────────────────────────────────────────────────────────────┐
│  Filters: [Status ▼] [CCD ▼]               [Search...] [+] │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  CN        │ Valid From │ Valid To   │ Revoked │ CCD   │   │
│  │────────────┼────────────┼────────────┼─────────┼───────│   │
│  │  user1     │ 2024-01-01 │ 2025-01-01 │    ✗    │   ✓   │   │
│  │  user2     │ 2024-01-01 │ 2024-12-01 │    ✓    │   ✗   │   │
│  │  user3     │ 2024-06-01 │ 2025-06-01 │    ✗    │   ✓   │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  [1] [2] [3] ... [10]                    Showing 1-20/150  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**Функции:**
- Фильтры: по статусу отзыва, наличию CCD
- Поиск по CN
- Сортировка по колонкам
- Пагинация
- Индикаторы статуса (✓/✗ цветные)
- Ссылка на детали аккаунта

### 3. Account Detail (/accounts/{cn})

Детальная информация об аккаунте.

**Layout:**
```
┌─────────────────────────────────────────────────────────────┐
│  ← Back to Accounts                                         │
│  Account: user1                                  [Status]   │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────────────┐  ┌─────────────────────────┐  │
│  │  Certificate Info       │  │  Connection Status      │  │
│  │  ─────────────────      │  │  ─────────────────      │  │
│  │  Valid From: 2024-01-01 │  │  Can Connect: ✓ Yes     │  │
│  │  Valid To: 2025-01-01   │  │  Certificate: ✓ Valid   │  │
│  │  Revoked: ✗ No          │  │  CCD File: ✓ Exists     │  │
│  │  CCD: ✓ Exists          │  │  Revoked: ✗ No          │  │
│  └─────────────────────────┘  └─────────────────────────┘  │
│                                                             │
│  Last Session                                               │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Status: Active                                       │   │
│  │  Connected: 2024-01-31 10:00                          │   │
│  │  IP: 1.2.3.4 (RU, Moscow)                             │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  Session History                                            │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Connected      │ Disconnected │ IP        │ Geo   │   │
│  │─────────────────┼──────────────┼───────────┼───────│   │
│  │  2024-01-31 10:00  │ Active    │ 1.2.3.4   │ RU/Moscow│
│  │  2024-01-30 15:30  │ 18:45     │ 5.6.7.8   │ DE/Berlin│
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  [Load More...]                                             │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**Компоненты:**
- Информация о сертификате (сроки действия, статус)
- Статус подключения (может ли подключиться)
- Информация о последней сессии
- История сессий с пагинацией
- Карта с маркерами подключений (опционально)

### 4. Sessions (/sessions)

Журнал всех сессий.

**Layout:**
```
┌─────────────────────────────────────────────────────────────┐
│  Filters: [Account ▼] [Status ▼] [From] [To]  [Search...]  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Account │ Connected │ Duration │ IP        │ Geo   │   │
│  │──────────┼───────────┼──────────┼───────────┼───────│   │
│  │  user1   │ 10:00:00  │ 2h 30m   │ 1.2.3.4   │ 🇷🇺    │   │
│  │  user2   │ 09:30:00  │ Active   │ 5.6.7.8   │ 🇩🇪    │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  [Export CSV]                           [1] [2] [3] ...     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**Функции:**
- Фильтры: по аккаунту, статусу, периоду
- Поиск по IP
- Сортировка
- Экспорт в CSV
- Пагинация
- Флаг страны вместо текста

### 5. Connection Attempts (/attempts)

Журнал неудачных попыток.

**Layout:**
```
┌─────────────────────────────────────────────────────────────┐
│  Filters: [Type ▼] [Account ▼] [From] [To]                  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Time       │ Account │ IP        │ Type       │ Reason│
│  │─────────────┼─────────┼───────────┼────────────┼───────│
│  │  10:05:23   │ user5   │ 9.8.7.6   │ Revoked    │ ...   │
│  │  09:45:12   │ user7   │ 5.4.3.2   │ No CCD     │ ...   │
│  │  09:30:00   │ -       │ 1.2.3.4   │ TLS Error  │ ...   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  Failure Types: [Revoked: 5] [No CCD: 3] [TLS: 2] ...      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**Функции:**
- Фильтры по типу ошибки, аккаунту, периоду
- Цветовая индикация типа ошибки
- Сводка по типам ошибок

### 6. Session Detail (/sessions/{id})

Детали конкретной сессии.

**Layout:**
```
┌─────────────────────────────────────────────────────────────┐
│  ← Back to Sessions                                         │
│  Session #123                                    [Active]   │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────────────┐  ┌─────────────────────────┐  │
│  │  Account                │  │  Timing                 │  │
│  │  ───────                │  │  ──────                 │  │
│  │  CN: user1              │  │  Connected: 10:00:00    │  │
│  │  Prefix: org_           │  │  Disconnected: -        │  │
│  │                         │  │  Duration: 2h 30m       │  │
│  └─────────────────────────┘  └─────────────────────────┘  │
│                                                             │
│  ┌─────────────────────────┐  ┌─────────────────────────┐  │
│  │  Connection             │  │  Traffic                │  │
│  │  ──────────             │  │  ───────                │  │
│  │  Source IP: 1.2.3.4     │  │  Sent: 1.2 MB           │  │
│  │  Country: Russia        │  │  Received: 5.6 MB       │  │
│  │  City: Moscow           │  │                         │  │
│  │  VPN IP: 10.8.0.5       │  │                         │  │
│  └─────────────────────────┘  └─────────────────────────┘  │
│                                                             │
│  [Map with location marker]                                 │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## Компоненты UI

### Навигация

```html
<nav class="navbar navbar-expand-lg navbar-dark bg-dark">
  <div class="container">
    <a class="navbar-brand" href="/">
      <i class="bi bi-shield-lock"></i> OpenVPN Monitor
    </a>
    <div class="navbar-nav">
      <a class="nav-link active" href="/">Dashboard</a>
      <a class="nav-link" href="/accounts">Accounts</a>
      <a class="nav-link" href="/sessions">Sessions</a>
      <a class="nav-link" href="/attempts">Attempts</a>
    </div>
    <div class="navbar-nav ms-auto">
      <span class="navbar-text">admin</span>
      <a class="nav-link" href="/logout">Logout</a>
    </div>
  </div>
</nav>
```

### Карточка метрики

```html
<div class="card bg-primary text-white">
  <div class="card-body">
    <div class="d-flex justify-content-between">
      <div>
        <h6 class="card-title">Active Sessions</h6>
        <h2 class="mb-0">15</h2>
      </div>
      <i class="bi bi-people-fill fs-1"></i>
    </div>
  </div>
</div>
```

### Таблица с DataTables

```html
<table class="table table-striped" id="accounts-table">
  <thead>
    <tr>
      <th>CN</th>
      <th>Prefix</th>
      <th>Valid To</th>
      <th>Revoked</th>
      <th>CCD</th>
    </tr>
  </thead>
  <tbody>
    <!-- Data loaded via AJAX -->
  </tbody>
</table>
```

### Индикаторы статуса

```html
<!-- Certificate Valid -->
<span class="badge bg-success"><i class="bi bi-check-circle"></i> Valid</span>

<!-- Certificate Revoked -->
<span class="badge bg-danger"><i class="bi bi-x-circle"></i> Revoked</span>

<!-- CCD Exists -->
<span class="badge bg-success"><i class="bi bi-file-earmark-check"></i> Yes</span>

<!-- Session Active -->
<span class="badge bg-primary"><i class="bi bi-broadcast"></i> Active</span>
```

## API интеграция

Все данные загружаются через REST API:

```javascript
// Пример загрузки данных для таблицы
async function loadAccounts(page = 1) {
  const response = await fetch(`/api/v1/accounts?page=${page}`, {
    headers: {
      'Authorization': 'Basic ' + btoa('admin:password')
    }
  });
  const data = await response.json();
  renderAccountsTable(data.data);
  renderPagination(data.meta);
}

// Real-time обновление активных сессий
setInterval(async () => {
  const response = await fetch('/api/v1/sessions/active');
  const data = await response.json();
  updateActiveSessionsWidget(data);
}, 30000); // каждые 30 секунд
```

## Responsive Design

- Mobile-first подход
- Таблицы с горизонтальной прокруткой на мобильных
- Карточки вместо таблиц для маленьких экранов
- Скрытие второстепенных колонок на мобильных
