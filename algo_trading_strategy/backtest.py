import pandas as pd
import pandas_ta as ta
from trading_strategy import heikin_ashi
import numpy as np

# --- Backtesting Parameters ---
INITIAL_CAPITAL = 100000
LOT_SIZE = 50
COMMISSION = 0.0  # Simplified for this example
STOPLOSS_POINTS = 15
TRAILING_STOPLOSS_INITIAL_PROFIT = 10
TRAILING_STOPLOSS_INCREMENT = 3

def get_option_price(underlying_price, strike_price, option_type='CE'):
    """A dummy function to simulate option prices."""
    # This is a highly simplified model. In reality, option prices are
    # determined by complex models like Black-Scholes.
    if option_type == 'CE':
        return max(0, underlying_price - strike_price)
    else:
        return max(0, strike_price - underlying_price)

def backtest(df):
    """Backtests the trading strategy on historical data."""
    capital = INITIAL_CAPITAL
    positions = []
    trades = []

    for i in range(1, len(df)):
        # --- Entry Conditions ---
        if (df['HA_Close'][i] > df['HA_Open'][i] and
                df['HA_Close'][i] > df[f'BBM_20_2.0_2.0'][i] and
                df['HA_Close'][i] > df[f'SUPERT_10_2.0'][i]):

            # --- Enter a simulated position ---
            underlying_price = df['close'][i]
            strike_price = round(underlying_price / 100) * 100
            entry_price = get_option_price(underlying_price, strike_price)

            positions.append({
                'entry_price': entry_price,
                'entry_time': df.index[i],
                'stoploss_price': entry_price - STOPLOSS_POINTS,
                'trailing_stoploss_price': None,
                'strike_price': strike_price
            })

        # --- Exit Conditions ---
        elif positions:
            underlying_price = df['close'][i]
            for p in positions:
                ltp = get_option_price(underlying_price, p['strike_price'])
                profit = ltp - p['entry_price']

                if p['trailing_stoploss_price'] is None and profit >= TRAILING_STOPLOSS_INITIAL_PROFIT:
                    p['trailing_stoploss_price'] = p['entry_price'] + 10

                if p['trailing_stoploss_price'] is not None:
                    while profit >= p['trailing_stoploss_price'] - p['entry_price'] + TRAILING_STOPLOSS_INCREMENT:
                        p['trailing_stoploss_price'] += TRAILING_STOPLOSS_INCREMENT


                if (p['trailing_stoploss_price'] is not None and ltp <= p['trailing_stoploss_price']) or \
                   (ltp <= p['stoploss_price']):
                    exit_price = ltp
                    profit = (exit_price - p['entry_price']) * LOT_SIZE
                    capital += profit
                    trades.append({
                        'entry_time': p['entry_time'],
                        'exit_time': df.index[i],
                        'entry_price': p['entry_price'],
                        'exit_price': exit_price,
                        'profit': profit
                    })
                    positions.remove(p)


    return pd.DataFrame(trades)

def main():
    """Main function to run the backtest."""
    # --- Load Sample Data ---
    # In a real scenario, you would fetch historical data from your broker
    # or a data provider. For this example, we'll create a sample CSV.
    df = pd.read_csv('algo_trading_strategy/historical_data.csv', parse_dates=['date'], index_col='date')


    # --- Calculate Indicators ---
    df_ha = heikin_ashi(df)
    df_ha.ta.bbands(length=20, std=2.0, append=True)
    df_ha.ta.supertrend(length=10, multiplier=2.0, append=True)


    # --- Run Backtest ---
    trades = backtest(df_ha)

    # --- Print Results ---
    if not trades.empty:
        print("--- Backtest Results ---")
        print(trades)
        print("\n--- Performance Metrics ---")
        print(f"Total Trades: {len(trades)}")
        print(f"Total Profit: {trades['profit'].sum():.2f}")
        print(f"Win Rate: {len(trades[trades['profit'] > 0]) / len(trades) * 100:.2f}%")
        print(f"Max Drawdown: # Not implemented in this simplified example")
    else:
        print("No trades were made during the backtest.")

if __name__ == "__main__":
    main()
