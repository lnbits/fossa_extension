from lnbits.db import Database

db = Database("ext_fossa")


async def m001_initial(db):
    """
    Initial fossa table.
    """
    await db.execute(
        f"""
        CREATE TABLE fossa.fossa (
            id TEXT NOT NULL PRIMARY KEY,
            key TEXT NOT NULL,
            title TEXT NOT NULL,
            wallet TEXT NOT NULL,
            currency TEXT NOT NULL,
            profit FLOAT NOT NULL,
            boltz BOOLEAN DEFAULT false,
            timestamp TIMESTAMP NOT NULL DEFAULT {db.timestamp_now}
        );
    """
    )
    await db.execute(
        f"""
        CREATE TABLE fossa.fossa_payment (
            id TEXT NOT NULL PRIMARY KEY,
            fossa_id TEXT NOT NULL,
            payment_hash TEXT,
            payload TEXT NOT NULL,
            pin INT,
            sats {db.big_int},
            timestamp TIMESTAMP NOT NULL DEFAULT {db.timestamp_now}
        );
    """
    )

async def m002_addcolumn_amount(db):
    await db.execute(
        """
        ALTER TABLE fossa.fossa_payment
        ADD COLUMN amount FLOAT NOT NULL;
        """
    )
