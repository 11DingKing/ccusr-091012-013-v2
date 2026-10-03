# 监管物资保管服务

该项目为监管仓、证物室和受控物资保管点提供服务端 API，覆盖人员授权、物资分类、批次登记、收发记录、审批、预警、审计日志与统计报表。数据保存在 SQLite，所有测试和接口验收均可在单个 Linux 应用容器内离线完成。

## 抽检方案管理（apps.inspection）

- 方案生命周期：草案（可编辑）→ 发布（写入生效区间）→ 撤回；已发布内容不可变，迭代须发新版本，同范围新版本生效时旧版本区间自动闭合。
- 到场核验：`POST /api/inspection/snapshots/fix/` 按物资类别、来源、批量、风险等级匹配当前生效方案，风险上升（risk_level=high）自动选用加严规则，并把方案编号/版本、命中规则全文、样本数量、检查项、判定阈值固化为快照。
- 快照幂等且不可变：同一批次（物资+批次号）只固定一次，重复核验返回既有快照；方案撤回或发新版均不影响旧批次，旧批次再次查询永远不会套用新方案。
- 一致性规则：小批量按方案固定的取整规则（向上/四舍五入/向下）计算，受最少样本数兜底且不超过批量；同严格度批量区间重叠在发布时拒绝，跨严格度重叠时加严优先；适用范围精确度不可比较（一方限定来源、另一方限定风险）拒绝发布；不合格后可发起加严复检，复检沿用快照冻结的规则并生成独立复检快照，首检记录不被覆盖。


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
