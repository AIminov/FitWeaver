# Garmin Fit Quick Start

1. Удаляет из Garmin Connect тренировки FitWeaver за период с 1 по 30 июня 2026 года включительно.  
Удаление реальное, потому что указан `--confirm`.

```powershell
python -m garmin_fit.cli garmin-calendar-delete \
--email your@email.com \
--password yourpassword \
--year 2026 \
--from-date 2026-06-01 \
--to-date 2026-06-30 \
--confirm
```

2. Проверяет, что будет загружено в Garmin Calendar из файла `Plan/plan.yaml`, но ничего реально не отправляет.  
Это безопасный предварительный просмотр всей загрузки.

```powershell
python -m garmin_fit.cli garmin-calendar \
--plan Plan/plan.yaml \
--email your@email.com \
--password yourpassword \
--year 2026 \
--dry-run
```

3. Загружает в Garmin Calendar тренировки из `Plan/plan.yaml` только за период с 1 по 30 июня 2026 года включительно.

```powershell
python -m garmin_fit.cli garmin-calendar \
--plan Plan/plan.yaml \
--email your@email.com \
--password yourpassword \
--year 2026 \
--from-date 2026-06-01 \
--to-date 2026-06-30
```

4. Показывает, какие FitWeaver-тренировки за период с 1 по 30 июня 2026 года будут удалены из Garmin Connect, но ничего не удаляет.

```powershell
python -m garmin_fit.cli garmin-calendar-delete \
--email your@email.com \
--password yourpassword \
--year 2026 \
--from-date 2026-06-01 \
--to-date 2026-06-30 \
--dry-run
```

5. Реально удаляет из Garmin Connect FitWeaver-тренировки за период с 1 по 30 июня 2026 года.

```powershell
python -m garmin_fit.cli garmin-calendar-delete \
--email your@email.com \
--password yourpassword \
--year 2026 \
--from-date 2026-06-01 \
--to-date 2026-06-30 \
--confirm
```

6. Удаляет все найденные тренировки из Garmin Connect, которые попадут в выборку команды, не только FitWeaver.  
Это самый опасный вариант, потому что он не ограничен диапазоном дат и не фильтрует только ваши YAML-загрузки.

```powershell
python -m garmin_fit.cli garmin-calendar-delete \
--email your@email.com \
--password yourpassword \
--all --confirm
```
