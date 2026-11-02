"""Recipe initialization and reminder writes share SQLite without snapshot upgrades."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from reminders_push_contract import init_db, db, now_iso, ensure_reminder_schema
from app.v10_routes import ensure_v10_schema


def main():
    init_db(); ensure_v10_schema(); ensure_reminder_schema()
    barrier = Barrier(3)
    def recipe_reader(index):
        barrier.wait()
        for _ in range(30):
            with db() as conn:
                ensure_v10_schema(conn)
                assert conn.execute('SELECT COUNT(*) FROM recipes').fetchone()[0] > 0
    def reminder_writer(index):
        barrier.wait()
        for turn in range(30):
            with db(immediate=True) as conn:
                conn.execute('INSERT OR REPLACE INTO app_meta(key,value) VALUES(?,?)', ('concurrent-reminder',str(turn)))
    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs = [pool.submit(recipe_reader,0),pool.submit(recipe_reader,1),pool.submit(reminder_writer,2)]
        for job in jobs:
            job.result(timeout=30)
    # A borrowed connection still belongs to its caller: no helper may commit it.
    try:
        with db() as conn:
            ensure_v10_schema(conn)
            conn.execute("INSERT INTO app_meta(key,value) VALUES('recipe-rollback-proof','pending')")
            raise RuntimeError('caller aborts')
    except RuntimeError:
        pass
    with db() as conn:
        assert conn.execute("SELECT 1 FROM app_meta WHERE key='recipe-rollback-proof'").fetchone() is None
        assert conn.execute("SELECT value FROM app_meta WHERE key='concurrent-reminder'").fetchone()[0] == '29'
    print('recipe/reminder concurrency passed: simultaneous initialization/writes and caller rollback')


if __name__ == '__main__':
    main()
