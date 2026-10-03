# 监管物资保管服务

该项目为监管仓、证物室和受控物资保管点提供服务端 API，覆盖人员授权、物资分类、批次登记、收发记录、审批、预警、审计日志与统计报表。数据保存在 SQLite，所有测试和接口验收均可在单个 Linux 应用容器内离线完成。

## 抽检方案与到场核验

- `POST /api/sampling-plans/` 创建抽检方案（草案），`PUT`/`DELETE` 仅草案可用
- `POST /api/sampling-plans/{id}/publish/` 发布方案，发布后按生效区间参与匹配
- `POST /api/sampling-plans/{id}/withdraw/` 撤回方案（需填写原因），撤回后不再参与新批次匹配，已固定快照不受影响
- `POST /api/inspections/fix/` 到场核验：按物资品类、来源和批量自动匹配方案并冻结快照；同一批次号重复核验返回原快照，不套用新方案
- `POST /api/inspections/{id}/complete/` 录入检查项结果，系统按结果推导判定结论
- 一致性规则：样本量统一向上取整并受最小/最大样本数与批量约束；同品类同来源上次判定不合格时下一批自动加严；规则重叠按优先级、来源精确度、区间跨度、创建先后确定性取舍

## 运行环境

- Python 3.11
- Django REST Framework
- SQLite

## 安装与初始化

```bash
python -m pip install -r backend/requirements.txt
cd backend
python manage.py migrate --run-syncdb
```

## 测试

```bash
cd backend
pytest -q
```

## 编译检查

```bash
python -m compileall -q backend
```

## API 验收

```bash
cd backend
python manage.py migrate --run-syncdb
python manage.py shell -c "from rest_framework.test import APIClient; from apps.authentication.models import User; u=User.objects.create_user('smoke','safe-pass',role='admin'); c=APIClient(); r=c.post('/api/auth/login/',{'username':'smoke','password':'safe-pass'},format='json'); print(r.status_code, bool(r.json()['data']['token']))"
```

## 容器

```bash
docker build -t custody-service .
docker run --rm custody-service
```
