import os
import time
from kiteconnect import KiteConnect
import pandas as pd
import pandas_ta as ta

# --- User Configuration ---
API_KEY = os.environ.get('KITE_API_KEY')
API_SECRET = os.environ.get('KITE_API_SECRET')
ACCESS_TOKEN = os.environ.get('KITE_ACCESS_TOKEN')

# --- Strategy Parameters ---
INSTRUMENT = "NIFTY 50"  # or "NIFTY BANK"
TIME_FRAME = "5minute"
BB_LENGTH = 20
BB_STDDEV = 2
ST_PERIOD = 10
ST_MULTIPLIER = 2
PREMIUM_TARGET = 160
STOPLOSS_POINTS = 15
TRAILING_STOPLOSS_INITIAL_PROFIT = 10
TRAILING_STOPLOSS_INCREMENT = 3
TRADE_START_TIME = "09:15"
TRADE_END_TIME = "12:45"
LOT_SIZE = 1


def heikin_ashi(df):
    """Converts a regular candlestick DataFrame to a Heikin-Ashi DataFrame."""
    df_ha = df.copy()
    df_ha['HA_Close'] = (df['open'] + df['high'] + df['low'] + df['close']) / 4
    df_ha['HA_Open'] = ((df['open'].shift(1) + df['close'].shift(1)) / 2).fillna(df_ha['HA_Close'])
    df_ha['HA_High'] = df_ha[['high', 'HA_Open', 'HA_Close']].max(axis=1)
    df_ha['HA_Low'] = df_ha[['low', 'HA_Open', 'HA_Close']].min(axis=1)
    return df_ha

def get_current_week_expiry(kite):
    """Gets the current week's Nifty options expiry date."""
    today = pd.to_datetime('today').date()
    instruments = kite.instruments("NFO")
    nifty_options = [
        i for i in instruments
        if i['name'] == 'NIFTY' and i['instrument_type'] == 'CE'
    ]
    expiry_dates = sorted(list(set([opt['expiry'] for opt in nifty_options])))
    for expiry in expiry_dates:
        if expiry.date() >= today:
            return expiry.date()
    return None

def get_nifty_futures_instrument_token(kite):
    """Gets the instrument token for Nifty futures."""
    instruments = kite.instruments("NFO")
    nifty_futures = [
        i for i in instruments
        if i['name'] == 'NIFTY' and i['segment'] == 'NFO-FUT'
    ]
    nifty_futures.sort(key=lambda x: x['expiry'])
    return nifty_futures[0]['instrument_token']

def find_option_contract(kite, underlying_price):
    """Finds the option contract with a premium near the target."""
    expiry = get_current_week_expiry(kite)
    if not expiry:
        print("Could not find current week's expiry.")
        return None

    instruments = kite.instruments("NFO")
    nifty_options = [
        i for i in instruments
        if i['name'] == 'NIFTY' and
           i['instrument_type'] == 'CE' and
           i['expiry'].date() == expiry
    ]

    # Get the LTP for all the options
    option_ltps = kite.ltp([opt['instrument_token'] for opt in nifty_options])

    # Find the option with the premium closest to the target
    closest_option = min(
        nifty_options,
        key=lambda x: abs(option_ltps[str(x['instrument_token'])]['last_price'] - PREMIUM_TARGET)
    )
    return closest_option

def main():
    """Main function to run the trading strategy."""
    if not all([API_KEY, API_SECRET]):
        print("Please set the KITE_API_KEY and KITE_API_SECRET environment variables.")
        return

    kite = KiteConnect(api_key=API_KEY)

    # --- Authentication ---
    if not ACCESS_TOKEN:
        print("First time setup: Please generate a request token.")
        print(f"Login URL: {kite.login_url()}")
        request_token = input("Enter the request token: ")
        try:
            data = kite.generate_session(request_token, api_secret=API_SECRET)
            ACCESS_TOKEN = data["access_token"]
            print(f"Access token generated. Please set it as an environment variable 'KITE_ACCESS_TOKEN' for future use.")
            kite.set_access_token(ACCESS_TOKEN)
        except Exception as e:
            print(f"Authentication failed: {e}")
            return
    else:
        kite.set_access_token(ACCESS_TOKEN)


    # --- Main Loop ---
    open_positions = []
    last_candle_timestamp = None
    while True:
        try:
            # --- Time Check ---
            current_time = time.strftime("%H:%M")
            if not (TRADE_START_TIME <= current_time < TRADE_END_TIME):
                if open_positions:
                    for position in open_positions[:]:
                        kite.place_order(
                            variety=kite.VARIETY_REGULAR,
                            exchange=kite.EXCHANGE_NFO,
                            tradingsymbol=position['tradingsymbol'],
                            transaction_type=kite.TRANSACTION_TYPE_SELL,
                            quantity=LOT_SIZE * position['lot_size'],
                            product=kite.PRODUCT_MIS,
                            order_type=kite.ORDER_TYPE_MARKET
                        )
                        print(f"Closing position for {position['tradingsymbol']} at end of day.")
                        open_positions.remove(position)
                time.sleep(60)  # Sleep for a minute
                continue

            # --- Get Nifty Futures Data ---
            nifty_futures_token = get_nifty_futures_instrument_token(kite)
            if not nifty_futures_token:
                print("Could not find Nifty futures instrument token.")
                return

            historical_data = kite.historical_data(
                instrument_token=nifty_futures_token,
                from_date=(pd.to_datetime('today') - pd.DateOffset(days=5)).strftime('%Y-%m-%d'),
                to_date=pd.to_datetime('today').strftime('%Y-%m-%d'),
                interval=TIME_FRAME
            )
            df = pd.DataFrame(historical_data)
            latest_candle = df.iloc[-1]

            if last_candle_timestamp and last_candle_timestamp == latest_candle['date']:
                time.sleep(1)
                continue

            last_candle_timestamp = latest_candle['date']

            # --- Calculate Indicators ---
            df_ha = heikin_ashi(df)
            df_ha.ta.bbands(length=BB_LENGTH, std=BB_STDDEV, append=True)
            df_ha.ta.supertrend(period=ST_PERIOD, multiplier=ST_MULTIPLIER, append=True)


            # --- Entry Conditions ---
            latest_candle = df_ha.iloc[-1]
            if (latest_candle['HA_Close'] > latest_candle['HA_Open'] and
                    latest_candle['HA_Close'] > latest_candle[f'BBM_{BB_LENGTH}_{float(BB_STDDEV)}'] and
                    latest_candle['HA_Close'] > latest_candle[f'SUPERT_{ST_PERIOD}_{float(ST_MULTIPLIER)}']) and not open_positions:

                # --- Find Option Contract ---
                nifty_ltp = kite.ltp([nifty_futures_token])[str(nifty_futures_token)]['last_price']
                option_contract = find_option_contract(kite, nifty_ltp)

                # --- Place Order ---
                order_id = kite.place_order(
                    variety=kite.VARIETY_REGULAR,
                    exchange=kite.EXCHANGE_NFO,
                    tradingsymbol=option_contract['tradingsymbol'],
                    transaction_type=kite.TRANSACTION_TYPE_BUY,
                    quantity=LOT_SIZE * option_contract['lot_size'],
                    product=kite.PRODUCT_MIS,
                    order_type=kite.ORDER_TYPE_MARKET
                )
                print(f"Order placed: {order_id}")

                # --- Add to open positions ---
                entry_price = kite.ltp([option_contract['instrument_token']])[str(option_contract['instrument_token'])]['last_price']
                open_positions.append({
                    'instrument_token': option_contract['instrument_token'],
                    'tradingsymbol': option_contract['tradingsymbol'],
                    'lot_size': option_contract['lot_size'],
                    'entry_price': entry_price,
                    'stoploss_price': entry_price - STOPLOSS_POINTS,
                    'trailing_stoploss_price': None
                })

            # --- Manage Open Positions ---
            for position in open_positions[:]:
                ltp = kite.ltp([position['instrument_token']])[str(position['instrument_token'])]['last_price']
                profit = ltp - position['entry_price']

                if position['trailing_stoploss_price'] is None and profit >= TRAILING_STOPLOSS_INITIAL_PROFIT:
                    position['trailing_stoploss_price'] = position['entry_price'] + 10
                    print(f"Trailing stoploss for {position['tradingsymbol']} activated at {position['trailing_stoploss_price']}")

                if position['trailing_stoploss_price'] is not None:
                    while profit >= position['trailing_stoploss_price'] - position['entry_price'] + TRAILING_STOPLOSS_INCREMENT:
                        position['trailing_stoploss_price'] += TRAILING_STOPLOSS_INCREMENT
                        print(f"Trailing stoploss for {position['tradingsymbol']} updated to {position['trailing_stoploss_price']}")

                if (position['trailing_stoploss_price'] is not None and ltp <= position['trailing_stoploss_price']) or \
                   (ltp <= position['stoploss_price']):
                    kite.place_order(
                        variety=kite.VARIETY_REGULAR,
                        exchange=kite.EXCHANGE_NFO,
                        tradingsymbol=position['tradingsymbol'],
                        transaction_type=kite.TRANSACTION_TYPE_SELL,
                        quantity=LOT_SIZE * position['lot_size'],
                        product=kite.PRODUCT_MIS,
                        order_type=kite.ORDER_TYPE_MARKET
                    )
                    print(f"Position closed for {position['tradingsymbol']}.")
                    open_positions.remove(position)

            # --- Sleep until the next candle ---
            time.sleep(1)

        except Exception as e:
            print(f"An error occurred: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()
