import json
import csv
from datetime import datetime, timedelta
from random import randint, uniform, choice, gauss
from faker import Faker
import os

fake = Faker('en_IN')

# Ensure output directory exists
os.makedirs('synthetic_data', exist_ok=True)

# Customer personas configuration
PERSONAS = {
    'healthy_retail': {
        'sector': 'Retail',
        'gst_monthly_range': (291667, 375000),  # ₹35L-45L annual / 12
        'gst_growth': 0.08,  # 8% YoY growth
        'gst_filing_delays': 0,  # No delays
        'upi_daily_range': (3000, 5000),  # ₹3K-5K daily
        'upi_transactions_daily': (80, 120),
        'adb_range': (600000, 900000),  # ₹6L-9L ADB
        'dscr': 2.1,
        'employees': (6, 10),
        'payroll_monthly': (80000, 120000),
        'payroll_delay': 0,
        'cheque_bounces': 0
    },
    'at_risk_services': {
        'sector': 'Services',
        'gst_monthly_range': (150000, 200000),  # ₹18L-24L annual / 12, declining
        'gst_growth': -0.05,  # -5% YoY decline
        'gst_filing_delays': 3,  # Late filings
        'upi_daily_range': (500, 1500),  # ₹500-1500 daily (sparse)
        'upi_transactions_daily': (20, 40),
        'adb_range': (100000, 250000),  # ₹1L-2.5L ADB (low)
        'dscr': 1.1,  # Weak
        'employees': (2, 4),
        'payroll_monthly': (30000, 50000),
        'payroll_delay': 2,  # Late EPFO deposits
        'cheque_bounces': 3
    },
    'ntc_clinic': {
        'sector': 'Healthcare Services',
        'gst_monthly_range': (0, 0),  # No GST (NTC)
        'gst_growth': 0,
        'gst_filing_delays': 0,
        'upi_daily_range': (15000, 25000),  # ₹15K-25K daily UPI
        'upi_transactions_daily': (30, 50),
        'adb_range': (200000, 400000),  # ₹2L-4L ADB
        'dscr': 1.5,  # Acceptable
        'employees': (2, 4),
        'payroll_monthly': (40000, 70000),
        'payroll_delay': 0,
        'cheque_bounces': 0
    },
    'mixed_signals_restaurant': {
        'sector': 'Food & Beverage',
        'gst_monthly_range': (375000, 541667),  # ₹45L-65L annual / 12, seasonal
        'gst_growth': 0.10,  # 10% growth but volatile
        'gst_filing_delays': 1,
        'upi_daily_range': (8000, 15000),  # ₹8K-15K daily
        'upi_transactions_daily': (150, 250),  # High frequency
        'adb_range': (150000, 300000),  # ₹1.5L-3L (low for turnover)
        'dscr': 1.4,
        'employees': (8, 15),
        'payroll_monthly': (100000, 180000),
        'payroll_delay': 1,
        'cheque_bounces': 1,
        'cash_withdrawals': True  # High cash withdrawals
    },
    'manufacturing_small': {
        'sector': 'Manufacturing',
        'gst_monthly_range': (458333, 625000),  # ₹55L-75L annual / 12
        'gst_growth': 0.07,
        'gst_filing_delays': 0,
        'upi_daily_range': (2000, 3500),  # ₹2K-3.5K daily (B2B)
        'upi_transactions_daily': (30, 60),  # Fewer but larger
        'adb_range': (900000, 1400000),  # ₹9L-14L ADB
        'dscr': 1.8,  # Strong
        'employees': (12, 18),
        'payroll_monthly': (150000, 220000),
        'payroll_delay': 0,
        'cheque_bounces': 0
    },
    'wholesale_trader': {
        'sector': 'Wholesale Trade',
        'gst_monthly_range': (291667, 416667),  # ₹35L-50L annual / 12
        'gst_growth': 0.06,
        'gst_filing_delays': 0,
        'upi_daily_range': (3000, 5000),
        'upi_transactions_daily': (60, 100),
        'adb_range': (400000, 600000),  # ₹4L-6L ADB
        'dscr': 2.3,  # Very strong
        'employees': (4, 8),
        'payroll_monthly': (60000, 100000),
        'payroll_delay': 0,
        'cheque_bounces': 0
    }
}

def generate_gst_data(customer_id, persona_key, year=2024):
    """Generate 12 months of GST filings"""
    persona = PERSONAS[persona_key]
    gst_data = []
    
    if persona['gst_monthly_range'][0] == 0:  # NTC (no GST)
        return gst_data
    
    base_monthly = persona['gst_monthly_range'][0]
    
    for month in range(1, 13):
        # Add YoY growth + some volatility
        growth_factor = 1 + (persona['gst_growth'] * (month / 12))
        volatility = gauss(0, base_monthly * 0.10)  # 10% volatility
        
        sales = base_monthly * growth_factor + volatility
        tax_rate = 0.18  # Assuming 18% GST
        tax_paid = sales * tax_rate
        
        # Filing delays
        filing_date = datetime(year, month, 20)  # Normal filing on 20th
        if persona['gst_filing_delays'] > 0:
            if randint(1, 5) <= persona['gst_filing_delays']:
                filing_date += timedelta(days=randint(5, 20))
        
        gst_data.append({
            'customer_id': customer_id,
            'month': month,
            'year': year,
            'gstr_sales': max(0, int(sales)),
            'tax_paid': max(0, int(tax_paid)),
            'filing_date': filing_date.strftime('%Y-%m-%d'),
            'is_delayed': filing_date.day > 20
        })
    
    return gst_data

def generate_upi_data(customer_id, persona_key, year=2024):
    """Generate daily UPI transactions for 12 months"""
    persona = PERSONAS[persona_key]
    upi_data = []
    
    daily_min, daily_max = persona['upi_daily_range']
    tx_min, tx_max = persona['upi_transactions_daily']
    
    start_date = datetime(year, 1, 1)
    
    for day_offset in range(365):  # Full year
        current_date = start_date + timedelta(days=day_offset)
        
        # Weekend/holiday effects
        is_weekend = current_date.weekday() >= 5
        is_holiday = current_date.month in [3, 8, 10, 12] and current_date.day in [1, 15, 25]  # Sample holidays
        
        # Adjust daily collections
        if is_weekend or is_holiday:
            activity_factor = 0.7
        else:
            activity_factor = 1.0 + gauss(0, 0.15)  # 15% volatility
        
        daily_collections = int((daily_min + uniform(0, daily_max - daily_min)) * activity_factor)
        num_transactions = randint(tx_min, tx_max)
        
        avg_ticket = daily_collections / num_transactions if num_transactions > 0 else 0
        
        upi_data.append({
            'customer_id': customer_id,
            'date': current_date.strftime('%Y-%m-%d'),
            'day_of_week': current_date.strftime('%A'),
            'collections': daily_collections,
            'num_transactions': num_transactions,
            'avg_ticket_size': int(avg_ticket)
        })
    
    return upi_data

def generate_aa_data(customer_id, persona_key, gst_data=None, year=2024):
    """Generate 12 months of bank statements (AA data).

    Bank credits are tied to the customer's own GST sales (± small noise) so the
    two sources actually reconcile, matching how a real business's revenue shows
    up as both GST turnover and bank deposits. NTC customers have no GST sales to
    key off, so they fall back to an ADB-derived credit estimate.

    Existing/proposed EMI are sized off the persona's documented target DSCR
    (e.g. 2.1 for healthy retail, 1.1 for at-risk services) rather than a fixed
    universal formula, so DSCR actually differs by persona instead of landing on
    the same value for everyone.
    """
    persona = PERSONAS[persona_key]
    aa_data = []
    gst_sales_by_month = {row['month']: row['gstr_sales'] for row in (gst_data or [])}

    adb_min, adb_max = persona['adb_range']
    base_adb = (adb_min + adb_max) / 2

    if gst_sales_by_month:
        avg_credit_base = sum(gst_sales_by_month.values()) / len(gst_sales_by_month)
    else:
        avg_credit_base = base_adb * 1.8  # NTC fallback: no GST sales to key off

    target_dscr = persona['dscr']
    total_debt_service = avg_credit_base / target_dscr
    existing_emi = int(total_debt_service * 0.6)
    proposed_emi = int(total_debt_service * 0.4)

    for month in range(1, 13):
        month_date = datetime(year, month, 1)

        # Monthly credits: this month's GST sales plus a small noise band, since
        # bank deposits don't mirror the GST return to the rupee. NTC customers
        # (no GST) keep the ADB-derived estimate.
        if month in gst_sales_by_month:
            monthly_credits = int(gst_sales_by_month[month] * uniform(0.95, 1.05))
        else:
            monthly_credits = int(base_adb * 1.8)

        # Monthly debits
        payroll = randint(*persona['payroll_monthly'])
        operating_expenses = int(monthly_credits * 0.45)
        tax_payments = int(monthly_credits * 0.12)
        monthly_debits = payroll + operating_expenses + tax_payments + existing_emi

        # Operating surplus
        operating_surplus = monthly_credits - monthly_debits

        # Average daily balance
        avg_daily_balance = randint(adb_min, adb_max)

        # DSCR calculation
        dscr = monthly_credits / (existing_emi + proposed_emi) if (existing_emi + proposed_emi) > 0 else 0

        # Cheque bounces
        cheque_returns = 0
        if persona['cheque_bounces'] > 0:
            if randint(1, 12) <= persona['cheque_bounces']:
                cheque_returns = randint(1, 2)
        
        # Cash withdrawals (flag high amounts for certain sectors)
        cash_withdrawals = int(monthly_credits * 0.05) if not persona.get('cash_withdrawals') else int(monthly_credits * 0.20)
        
        aa_data.append({
            'customer_id': customer_id,
            'month': month,
            'year': year,
            'month_date': month_date.strftime('%Y-%m-%d'),
            'total_credits': monthly_credits,
            'total_debits': monthly_debits,
            'payroll_paid': payroll,
            'operating_expenses': operating_expenses,
            'tax_payments': tax_payments,
            'existing_emi': existing_emi,
            'operating_surplus': operating_surplus,
            'avg_daily_balance': avg_daily_balance,
            'dscr': round(dscr, 2),
            'cheque_returns': cheque_returns,
            'cash_withdrawals': cash_withdrawals
        })
    
    return aa_data

def generate_epfo_data(customer_id, persona_key, year=2024):
    """Generate 12 months of EPFO payroll records"""
    persona = PERSONAS[persona_key]
    epfo_data = []

    emp_min, emp_max = persona['employees']
    payroll_min, payroll_max = persona['payroll_monthly']

    starting_employees = randint(emp_min, emp_max)
    employee_count = starting_employees

    # Headcount drifts persona-appropriately (growing, shrinking, or flat) rather
    # than resampling the whole distribution each month, since real headcount
    # changes gradually via hires/attrition, not full independent redraws.
    if persona['gst_growth'] > 0.03:
        trend_direction = 1
    elif persona['gst_growth'] < -0.03:
        trend_direction = -1
    else:
        trend_direction = 0

    for month in range(1, 13):
        # Gentle month-to-month headcount drift, biased by the persona's trend
        if month > 1:
            change_roll = randint(1, 100)
            if trend_direction > 0 and change_roll <= 20:
                employee_count += 1
            elif trend_direction < 0 and change_roll <= 20:
                employee_count = max(1, employee_count - 1)
            elif trend_direction == 0 and change_roll <= 8:
                # Mean-reverting: nudge back toward the starting headcount rather
                # than an unbiased random walk, so "stable" personas stay stable
                # instead of drifting away over 12 months by chance.
                if employee_count > starting_employees:
                    employee_count -= 1
                elif employee_count < starting_employees:
                    employee_count += 1
                else:
                    employee_count = max(1, employee_count + choice([-1, 1]))

        # Monthly payroll
        monthly_payroll = randint(payroll_min, payroll_max)
        avg_wage = monthly_payroll // employee_count if employee_count > 0 else 0
        
        # Contribution timeliness
        contribution_date = datetime(year, month, 15)  # Normal: 15th of month
        is_late = False
        if persona['payroll_delay'] > 0:
            if randint(1, 12) <= persona['payroll_delay']:
                contribution_date += timedelta(days=randint(5, 15))
                is_late = True
        
        # Employee churn (% leaving)
        employee_churn = 0
        if randint(1, 100) < 15:  # 15% chance of some churn
            employee_churn = randint(0, 1)
        
        epfo_data.append({
            'customer_id': customer_id,
            'month': month,
            'year': year,
            'employee_count': employee_count,
            'monthly_payroll': monthly_payroll,
            'avg_wage': avg_wage,
            'contribution_date': contribution_date.strftime('%Y-%m-%d'),
            'is_late_contribution': is_late,
            'employee_churn': employee_churn
        })
    
    return epfo_data

def generate_customer_profile(persona_key, index):
    """Generate basic customer info"""
    sector = PERSONAS[persona_key]['sector']
    
    customer_names = {
        'Retail': f"{fake.word().title()} Retail Store",
        'Services': f"{fake.word().title()} Services",
        'Healthcare Services': f"{fake.first_name()} Clinic",
        'Food & Beverage': f"{fake.word().title()} Restaurant",
        'Manufacturing': f"{fake.word().title()} Manufacturing",
        'Wholesale Trade': f"{fake.word().title()} Traders"
    }
    
    return {
        'customer_id': f'CUST_{index:03d}',
        'business_name': customer_names.get(sector, f"{fake.word().title()} Business"),
        'sector': sector,
        'persona': persona_key,
        'gst_number': f"{randint(10, 36)}{fake.postcode()}{fake.bothify('???')}{randint(100, 999)}" if persona_key != 'ntc_clinic' else 'NOT_REGISTERED',
        'pan': fake.bothify('?????####?'),
        'registration_date': fake.date_between(start_date='-5y').strftime('%Y-%m-%d')
    }

def main():
    """Generate all synthetic data"""
    print("🔧 Generating MSME Financial Health Card Synthetic Data...\n")
    
    all_customers = []
    all_gst = []
    all_upi = []
    all_aa = []
    all_epfo = []
    
    persona_keys = list(PERSONAS.keys())
    
    for idx, persona_key in enumerate(persona_keys, 1):
        print(f"  Generating {persona_key.replace('_', ' ').title()}...")
        
        # Customer profile
        customer = generate_customer_profile(persona_key, idx)
        all_customers.append(customer)
        
        # Financial data
        gst = generate_gst_data(customer['customer_id'], persona_key)
        upi = generate_upi_data(customer['customer_id'], persona_key)
        aa = generate_aa_data(customer['customer_id'], persona_key, gst_data=gst)
        epfo = generate_epfo_data(customer['customer_id'], persona_key)
        
        all_gst.extend(gst)
        all_upi.extend(upi)
        all_aa.extend(aa)
        all_epfo.extend(epfo)
    
    # Write JSON files
    print("\n📁 Writing JSON files...")
    with open('synthetic_data/customers.json', 'w') as f:
        json.dump(all_customers, f, indent=2)
    
    with open('synthetic_data/gst_filings.json', 'w') as f:
        json.dump(all_gst, f, indent=2)
    
    with open('synthetic_data/upi_transactions.json', 'w') as f:
        json.dump(all_upi, f, indent=2)
    
    with open('synthetic_data/bank_statements.json', 'w') as f:
        json.dump(all_aa, f, indent=2)
    
    with open('synthetic_data/epfo_payroll.json', 'w') as f:
        json.dump(all_epfo, f, indent=2)
    
    # Write CSV files
    print("📄 Writing CSV files...")
    
    # Customers CSV
    with open('synthetic_data/customers.csv', 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=all_customers[0].keys())
        writer.writeheader()
        writer.writerows(all_customers)
    
    # GST CSV
    if all_gst:
        with open('synthetic_data/gst_filings.csv', 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=all_gst[0].keys())
            writer.writeheader()
            writer.writerows(all_gst)
    
    # UPI CSV
    if all_upi:
        with open('synthetic_data/upi_transactions.csv', 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=all_upi[0].keys())
            writer.writeheader()
            writer.writerows(all_upi[:30])  # Sample to keep file size reasonable
    
    # AA CSV
    if all_aa:
        with open('synthetic_data/bank_statements.csv', 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=all_aa[0].keys())
            writer.writeheader()
            writer.writerows(all_aa)
    
    # EPFO CSV
    if all_epfo:
        with open('synthetic_data/epfo_payroll.csv', 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=all_epfo[0].keys())
            writer.writeheader()
            writer.writerows(all_epfo)
    
    # Summary
    print("\n✅ Synthetic Data Generated Successfully!\n")
    print("📊 Data Summary:")
    print(f"  Customers: {len(all_customers)}")
    print(f"  GST records: {len(all_gst)}")
    print(f"  UPI transactions: {len(all_upi)}")
    print(f"  Bank statements: {len(all_aa)}")
    print(f"  EPFO records: {len(all_epfo)}")
    print(f"\n📂 Output: synthetic_data/")
    print("  - customers.json / customers.csv")
    print("  - gst_filings.json / gst_filings.csv")
    print("  - upi_transactions.json / upi_transactions.csv")
    print("  - bank_statements.json / bank_statements.csv")
    print("  - epfo_payroll.json / epfo_payroll.csv")

if __name__ == '__main__':
    main()
