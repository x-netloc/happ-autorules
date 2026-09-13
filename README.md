# happ-autorules

Автоматически обновляемые routing-профили для Happ.

Категории и профили маршрутизации берутся из единого репозитория
[`autorules`](https://github.com/x-netloc/autorules). Здесь они преобразуются в
Happ JSON, готовые `happ://routing/...` deeplinks и проверенные GeoIP/GeoSite
DAT-файлы.

## Готовые профили

| Профиль | Маршрутизация | Добавить и активировать |
| --- | --- | --- |
| `bypass-blacklist` | Заблокированное и выбранные зарубежные сервисы через прокси, остальное напрямую | [`onadd`](https://raw.githubusercontent.com/x-netloc/happ-autorules/dist/links/bypass-blacklist.onadd.txt) |
| `freedom-no-ru` | Российские и локальные ресурсы напрямую, остальное через прокси | [`onadd`](https://raw.githubusercontent.com/x-netloc/happ-autorules/dist/links/freedom-no-ru.onadd.txt) |
| `freedom-no-ru-no-ads` | То же самое с блокировкой рекламы | [`onadd`](https://raw.githubusercontent.com/x-netloc/happ-autorules/dist/links/freedom-no-ru-no-ads.onadd.txt) |

Откройте нужный `onadd`, скопируйте всю строку `happ://...` и откройте её в
браузере на устройстве с Happ. В каталоге `links/` также есть варианты
`*.add.txt`, которые добавляют профиль без принудительной активации.

Для интеграции с подпиской содержимое deeplink можно передать HTTP-заголовком
`routing` или добавить отдельной строкой в тело подписки.

## Что публикуется

Ветка [`dist`](https://github.com/x-netloc/happ-autorules/tree/dist) содержит:

```text
geosite.dat                   GeoSite-база из upstream
geoip.dat                     GeoIP-база из upstream
SHA256SUMS                    контрольные суммы DAT
profiles/<profile>.json       читаемый Happ routing profile
links/<profile>.add.txt       добавить профиль
links/<profile>.onadd.txt     добавить и активировать профиль
INDEX.md                      индекс готовых профилей
```

В профилях включён `UseChunkFiles`, чтобы Happ вырезал только используемые
категории перед передачей DAT-файлов ядру. `LastUpdated` изменяется только при
реальном изменении upstream, `autorules` или адаптера.

## Приоритет правил в Happ

Happ хранит правила в трёх общих группах и поддерживает один `RouteOrder` на
профиль. Поэтому адаптер использует нативный порядок клиента:

- если профиль содержит блокировку — `block-direct-proxy`;
- для остальных текущих профилей — `direct-proxy-block`.

Исходный порядок `autorules` и порядок других клиентов при этом не меняются.

## Обновления

GitHub Actions каждый час проверяет upstream, commit `autorules` и код
адаптера. Категории сверяются с реальными DAT перед публикацией. Новые профили
автоматически получают JSON и оба deeplink-варианта.

Формат соответствует официальной
[документации Happ Routing](https://www.happ.su/main/ru/dev-docs/routing).
