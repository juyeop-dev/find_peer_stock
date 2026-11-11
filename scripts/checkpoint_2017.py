"""Combine the independently resumable financial and daily-history evidence."""
import sqlite3

import stock_information as info
import stock_chart_history as charts


def main():
    state = charts.ROOT / 'data/tmp_2017'
    db = info.open_database(state)
    source = sqlite3.connect(charts.ROOT / 'data/tmp_2017_history/information.sqlite')
    db.execute('CREATE TABLE IF NOT EXISTS history_2017_updates(ticker TEXT PRIMARY KEY,value TEXT NOT NULL)')
    db.executemany('INSERT OR REPLACE INTO history_2017_updates VALUES (?,?)', source.execute('SELECT ticker,value FROM history_2017_updates').fetchall())
    db.commit()
    source.close()
    charts.DATABASE = charts.ROOT / 'data/tmp_2017_history/history.sqlite'
    history = charts.database()
    rows = charts.roster()
    info.checkpoint(db, rows, history)
    print(f'Combined financial and price evidence for {len(rows)} detail listings')
    history.close()
    db.close()


if __name__ == '__main__':
    main()
