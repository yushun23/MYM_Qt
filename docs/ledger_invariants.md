# 账务不变性（Ledger Invariants）

## 不可违背的规则

1. **金额守恒**: 每笔已过账交易的 debit 总额 == credit 总额
2. **余额可重算**: current_balance = opening_balance + SUM(已过账交易对账户的影响)
3. **类型安全**: 金额使用 Decimal(Numeric(18,2))，禁止 float
4. **账户保护**: 普通记账不可操作 receivable / investment_linked 类型账户
5. **事务原子性**: 所有资金写入在一个数据库事务中完成
6. **审计追踪**: 每个修改都产生 AuditLog 记录
7. **软删除优先**: 交易先作废(void)，不走物理删除

## 禁止事项

- ❌ UI 层直接执行 SQL
- ❌ 跨线程共享 SQLAlchemy Session
- ❌ 浮点数用于金额计算
- ❌ 绕过 CreateTransactionUseCase 写入交易
- ❌ 对旧 .mym 文件执行破坏性操作
- ❌ 将 API Key 或密码写入日志
