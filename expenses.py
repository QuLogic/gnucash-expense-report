#!/usr/bin/env python2

# Run as: gnucash-env ./expenses.py
# NOTE: GnuCash only works with Python 2.
from __future__ import (absolute_import, division, print_function)

import argparse
from collections import defaultdict
import datetime
from decimal import Decimal
import sys

try:
    import gnucash
except ImportError:
    print('You must run this script in the GnuCash environment.',
          file=sys.stderr)
    print('    gnucash-env %s' % (sys.argv[0], ), file=sys.stderr)
    exit(1)

from gnucash.gnucash_core_c import gnc_commodity_get_nice_symbol


TWOPLACES = Decimal(10) ** -2
SIXPLACES = Decimal(10) ** -6
# We should be able to get this from GnuCash, but I don't want to implement
# some full currency calculation.
FOREIGN = 'US$'
LOCAL = '$'


def read_account_transactions(account):
    acc_data = [(datetime.date.fromtimestamp(split.parent.GetDate()),
                 split.parent.GetNum(),
                 split) for split in account.GetSplitList()]

    for child in account.get_children():
        child_data = read_account_transactions(child)
        acc_data.extend(child_data)

    return acc_data


parser = argparse.ArgumentParser(
    description='Produce expense report from GnuCash database.')
parser.add_argument('input', help='GnuCash database file or SQL path.')
parser.add_argument('--accounts', nargs='+',
                    default=['Assets', 'Bank', 'Liabilities'],
                    help='Accounts to use for finding transactions.')
parser.add_argument('--output', help='Output PDF file name.')
args = parser.parse_args()

# GnuCash uses '.' in the full name lookup for some reason
args.accounts = [name.replace(':', '.') for name in args.accounts]

data = []

print('Reading data from "%s" ...' % (args.input, ))
sess = gnucash.Session(args.input, is_new=False)

try:
    root = sess.book.get_root_account()
    for name in args.accounts:
        acc = root
        for sub in name.split('.'):
            acc = acc.lookup_by_name(sub)

        acc_data = read_account_transactions(acc)
        data.extend(acc_data)

finally:
    sess.end()

expenses = defaultdict(list)

print('Transactions')
print('============')
data = sorted(set(data))  # FIXME: Splits are not unique, unfortunately.
for date, num, split in data:
    trans = split.parent
    other = split.GetOtherSplit()

    val = split.GetValue()
    price = split.GetSharePrice()
    curr = split.account.get_currency_or_parent()

    print('%s - %s' % (date, trans.GetDescription()))

    if other:
        other_name = other.account.get_full_name()
        other_curr = other.account.get_currency_or_parent()
        foreign = other.GetValue()
        local = val.div(price, 1000, 0).neg()
        print('\t%s %s%s' % (
            other_name,
            gnc_commodity_get_nice_symbol(other_curr),
            foreign))
        print('\t%s %s%s' % (
            split.account.get_full_name(),
            gnc_commodity_get_nice_symbol(curr),
            local))

        other_name = other_name.split('.')
        cat = other_name[1]
        acc = other_name[-1]
        expenses[cat].append((acc, local, foreign))
    else:
        print('\t-')
        print('\t%s %s%s' % (
            split.account.get_full_name(),
            gnc_commodity_get_nice_symbol(curr),
            val.div(price, 1000, 0).neg()))
print()

print('Expenses')
print('========')
expense_local = Decimal()
expense_foreign = Decimal()
for k, v in sorted(expenses.items()):
    print('\t' + k)

    local_group = defaultdict(Decimal)
    foreign_group = defaultdict(Decimal)
    for name, local, foreign in v:
        local_group[name] += Decimal(local.num()) / Decimal(local.denom())
        foreign_group[name] += Decimal(foreign.num()) / Decimal(foreign.denom())

    local_sum = Decimal()
    foreign_sum = Decimal()
    for name in sorted(local_group):
        local_sum += local_group[name]
        foreign_sum += foreign_group[name]
        print('\t\t%s\t%s%s\t%s%s' % (
            name,
            FOREIGN, foreign_group[name].quantize(TWOPLACES),
            LOCAL, local_group[name].quantize(TWOPLACES)))
    print('\t\tTotal\t\t\t%s%s\t%s%s' % (FOREIGN,
                                         foreign_sum.quantize(TWOPLACES),
                                         LOCAL,
                                         local_sum.quantize(TWOPLACES)))
    expense_local += local_sum
    expense_foreign += foreign_sum

print()
print('\tGrand Total\t\t%s%s\t%s%s' % (FOREIGN,
                                       expense_foreign.quantize(TWOPLACES),
                                       LOCAL,
                                       expense_local.quantize(TWOPLACES)))
print()

if not args.output:
    exit()

from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.pagesizes import inch, letter
from reportlab.lib.styles import getSampleStyleSheet

print('Writing report to %s ...' % (args.output, ))

styles = getSampleStyleSheet()

doc = SimpleDocTemplate(args.output, pagesize=letter)
elements = []

header = Paragraph('Transactions', styles['Heading1'])
elements.append(header)

balance = Decimal(0)
rows = [['Date', 'Description', 'Credit', 'Debit', 'Balance']]
ts = TableStyle([('ALIGNMENT', (2, 0), (-1, -1), 'RIGHT'),
                 ('LINEBELOW', (0, 0), (-1, 0), 1.0, colors.grey)])
data = sorted(set(data))  # FIXME: Splits are not unique, unfortunately.
for date, num, split in data:
    trans = split.parent
    other = split.GetOtherSplit()

    val = split.GetValue()
    price = split.GetSharePrice()
    rate = (Decimal(price.denom()) / Decimal(price.num())).quantize(SIXPLACES)
    curr = split.account.get_currency_or_parent()

    rows.append([date,
                 trans.GetDescription(),
                 None,
                 None])

    if other:
        other_name = other.account.get_full_name().replace('.', ':')
        other_curr = other.account.get_currency_or_parent()
        foreign = other.GetValue()
        other_val = gnc_commodity_get_nice_symbol(other_curr) + str(foreign)
        local = val.div(price, 1000, 0).neg()
        local_val = gnc_commodity_get_nice_symbol(curr) + str(local)
    else:
        other_name = '-'
        other_val = '-'
        local = val.div(price, 1000, 0).neg()
        local_val = gnc_commodity_get_nice_symbol(curr) + str(local)
        rate = 1

    balance += (Decimal(local.num()) / Decimal(local.denom())).quantize(TWOPLACES)

    rows.append([None,
                 other_name,
                 other_val])
    rows.append([None,
                 split.account.get_full_name().replace('.', ':') +
                 (' @ ' + str(rate) if rate != 1 else ''),
                 None,
                 local_val])

    rows.append([None, None, None, None, LOCAL + str(balance)])

rows.append(['Grand Total', None, None, None, LOCAL + str(balance)])
ts.add('LINEABOVE', (0, -1), (-1, -1), 1.0, colors.black)
ts.add('FONT', (0, -1), (-1, -1), 'Helvetica-BoldOblique')

t = Table(rows,
          [1 * inch, 3.25 * inch, 0.75 * inch, 0.75 * inch, 0.75 * inch],
          repeatRows=1)
t.setStyle(ts)
elements.append(t)

space = PageBreak()
elements.append(space)

header = Paragraph('Expenses', styles['Heading1'])
elements.append(header)

expense_local = Decimal()
expense_foreign = Decimal()
for k, v in sorted(expenses.items()):
    header = Paragraph(k, styles['Heading2'])
    elements.append(header)

    local_group = defaultdict(Decimal)
    foreign_group = defaultdict(Decimal)
    for name, local, foreign in v:
        local = Decimal(local.num()) / Decimal(local.denom())
        local_group[name] += local.quantize(TWOPLACES)
        foreign = Decimal(foreign.num()) / Decimal(foreign.denom())
        foreign_group[name] += foreign.quantize(TWOPLACES)

    rows = []
    local_sum = Decimal()
    for name in sorted(local_group):
        local_val = local_group[name]
        foreign_val = foreign_group[name]

        local_sum += local_val

        rows.append([name,
                     (FOREIGN + str(foreign_val))
					 if foreign_val != local_val else 'N/A',
                     LOCAL + str(local_val)])

    rows.append(['Total',
                 '',
                 LOCAL + str(local_sum)])

    t = Table(rows, [4.25 * inch, 1.25 * inch, 1 * inch])
    t.setStyle(TableStyle([('ALIGNMENT', (1, 0), (-1, -1), 'RIGHT'),
                           ('INNERGRID', (0, 0), (-1, -1), 0.25, colors.grey),
                           ('LINEABOVE', (0, -1), (-1, -1), 1.0, colors.black),
                           ('FONT', (0, -1), (-1, -1), 'Helvetica-BoldOblique')]))
    elements.append(t)

    expense_local += local_sum
    expense_foreign += foreign_sum

#print('\tGrand Total\t\t%s%s\t%s%s' % (FOREIGN,
#                                       expense_foreign.quantize(TWOPLACES),
#                                       LOCAL,
#                                       expense_local.quantize(TWOPLACES)))

doc.build(elements)
