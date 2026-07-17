Created At: 2026-07-17T13:39:51Z
Completed At: 2026-07-17T13:39:51Z
File Path: `file:///c:/Users/PC/Desktop/doova_one_view/odoo_backend/venv/doova_one_view/doova_one_view/api/accounting/service.py`
Total Lines: 1644
Total Bytes: 70316
Showing lines 1450 to 1600
The following code has been modified to include a line number before every line, in the format: <line_number>: <original_line>. Please note that any changes targeting the original code should remove the line number, colon, and leading space.
1450:                 limit=limit,
1451:                 offset=offset,
1452:             ).model_dump()
1453:             
1454:         return await asyncio.to_thread(_get)
1455: 
1456:     @staticmethod
1457:     async def get_journal_cards(
1458:         tenant_id: str,
1459:         start_date: str = None,
1460:         end_date: str = None,
1461:         company_ids: list[int] = None,
1462:         base_currency: str = None,
1463:         limit: int = 50,
1464:         offset: int = 0
1465:     ) -> dict[str, Any]:
1466:         def _get():
1467:             from odoo_app.models import AccountJournal, AccountMove, BankStatement, AccountMoveLine
1468:             from django.db.models import Sum, Q, Count
1469:             from datetime import date
1470:             
1471:             rate_map = _get_rate_map()
1472:             effective_base = (base_currency or "XAF").upper()
1473:             
1474:             qs = AccountJournal.objects.filter(tenant_id=tenant_id)
1475:             if company_ids:
1476:                 qs = qs.filter(company_id__in=company_ids)
1477:                 
1478:             total = qs.count()
1479:             journals = qs.select_related('company').order_by('name')[offset:offset+limit]
1480:             
1481:             cards = []
1482:             for j in journals:
1483:                 company_currency = j.company.currency_code if (j.company and j.company.currency_code) else "COMPANY_BASE"
1484:                 if not company_currency or company_currency == "COMPANY_BASE":
1485:                     company_currency = "XAF"
1486:                 
1487:                 rate = _get_conversion_rate(company_currency, effective_base, rate_map)
1488:                 
1489:                 metrics = {
1490:                     "balance": 0.0,
1491:                     "latest_statement_balance": 0.0,
1492:                     "gl_balance": 0.0,
1493:                     "outstanding_payments": 0.0,
1494:                     "outstanding_receipts": 0.0,
1495:                     "unpaid_count": 0,
1496:                     "unpaid_amount": 0.0,
1497:                     "draft_count": 0,
1498:                     "draft_amount": 0.0,
1499:                     "late_count": 0,
1500:                     "late_amount": 0.0
1501:                 }
1502:                 
1503:                 j_type = j.type or "general"
1504:                 
1505:                 if j_type in ["bank", "cash"]:
1506:                     stmt_qs = BankStatement.objects.filter(tenant_id=tenant_id, journal=j)
1507:                     if start_date:
1508:                         stmt_qs = stmt_qs.filter(date__gte=start_date)
1509:                     if end_date:
1510:                         stmt_qs = stmt_qs.filter(date__lte=end_date)
1511:                     
1512:                     latest_statement = stmt_qs.order_by('-date', '-id').first()
1513:                     
1514:                     if latest_statement:
1515:                         metrics["latest_statement_balance"] = _to_float(latest_statement.balance_end_real) * rate
1516:                         metrics["balance"] = metrics["latest_statement_balance"]
1517:                     
1518:                     if hasattr(j, 'default_account_code') and j.default_account_code:
1519:                         gl_qs = AccountMoveLine.objects.filter(
1520:                             tenant_id=tenant_id,
1521:                             account_code=j.default_account_code,
1522:                             account_move__state='posted'
1523:                         )
1524:                     else:
1525:                         gl_qs = AccountMoveLine.objects.filter(
1526:                             tenant_id=tenant_id,
1527:                             account_move__journal=j,
1528:                             account_move__state='posted'
1529:                         )
1530:                     if start_date:
1531:                         gl_qs = gl_qs.filter(account_move__date__gte=start_date)
1532:                     if end_date:
1533:                         gl_qs = gl_qs.filter(account_move__date__lte=end_date)
1534:                         
1535:                     gl_agg = gl_qs.aggregate(
1536:                         total_debit=Sum('debit'),
1537:                         total_credit=Sum('credit')
1538:                     )
1539:                     metrics["gl_balance"] = (_to_float(gl_agg['total_debit']) - _to_float(gl_agg['total_credit'])) * rate
1540:                     
1541:                     if not latest_statement:
1542:                         metrics["balance"] = metrics["gl_balance"]
1543:                     
1544:                 elif j_type in ["sale", "purchase"]:
1545:                     move_type_filter = "out_invoice" if j_type == "sale" else "in_invoice"
1546:                     
1547:                     moves_qs = AccountMove.objects.filter(
1548:                         tenant_id=tenant_id,
1549:                         journal=j,
1550:                         move_type=move_type_filter
1551:                     )
1552:                     if start_date:
1553:                         moves_qs = moves_qs.filter(date__gte=start_date)
1554:                     if end_date:
1555:                         moves_qs = moves_qs.filter(date__lte=end_date)
1556:                     
1557:                     draft_agg = moves_qs.filter(state='draft').aggregate(
1558:                         count=Count('id'),
1559:                         amount=Sum('amount_total')
1560:                     )
1561:                     metrics["draft_count"] = draft_agg['count'] or 0
1562:                     metrics["draft_amount"] = _to_float(draft_agg['amount']) * rate
1563:                     
1564:                     unpaid_qs = moves_qs.filter(state='posted').exclude(payment_state__in=['paid', 'reversed'])
1565:                     unpaid_agg = unpaid_qs.aggregate(
1566:                         count=Count('id'),
1567:                         amount=Sum('amount_residual')
1568:                     )
1569:                     metrics["unpaid_count"] = unpaid_agg['count'] or 0
1570:                     metrics["unpaid_amount"] = _to_float(unpaid_agg['amount']) * rate
1571:                     
1572:                     late_agg = unpaid_qs.filter(invoice_date_due__lt=date.today()).aggregate(
1573:                         count=Count('id'),
1574:                         amount=Sum('amount_residual')
1575:                     )
1576:                     metrics["late_count"] = late_agg['count'] or 0
1577:                     metrics["late_amount"] = _to_float(late_agg['amount']) * rate
1578: 
1579:                 else:
1580:                     # General journals: misc. operations, stock, voucher, etc.
1581:                     gen_moves_qs = AccountMove.objects.filter(
1582:                         tenant_id=tenant_id,
1583:                         journal=j
1584:                     )
1585:                     if start_date:
1586:                         gen_moves_qs = gen_moves_qs.filter(date__gte=start_date)
1587:                     if end_date:
1588:                         gen_moves_qs = gen_moves_qs.filter(date__lte=end_date)
1589: 
1590:                     # Draft entries
1591:                     draft_agg = gen_moves_qs.filter(state='draft').aggregate(
1592:                         count=Count('id'),
1593:                         amount=Sum('amount_total')
1594:                     )
1595:                     metrics["draft_count"] = draft_agg['count'] or 0
1596:                     metrics["draft_amount"] = _to_float(draft_agg['amount']) * rate
1597: 
1598:                     # GL balance (net debit - credit) from posted move lines
1599:                     gl_qs = AccountMoveLine.objects.filter(
1600:                         tenant_id=tenant_id,
The above content does NOT show the entire file contents. If you need to view any lines of the file which were not shown to complete your task, call this tool again to view those lines.
