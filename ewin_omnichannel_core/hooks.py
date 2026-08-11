import logging

_logger = logging.getLogger(__name__)

# Conversations per pass. Bounds the ORM cache on a database whose whole
# message history would not fit in memory at once.
BACKFILL_BATCH_SIZE = 200


def backfill_existing_history(env):
    """Mirror the history of conversations that were already linked.

    Linking a conversation is what fills a customer's chatter, and that only
    happens on a link *change*. A conversation created by the routing service
    gets its contact at creation, so a database that ran EWIN Inbox before
    this feature existed holds conversations whose texts never reached the
    contact — and no operator gesture will ever fix them, because the link is
    already correct.

    Idempotent by construction: the service skips a message that already has
    a copy on that target, so running this twice changes nothing.

    Deliberately does not commit. Odoo commits once the install or upgrade
    succeeds; committing here would leave half-mirrored data behind a module
    load that then rolled back.
    """
    conversations = env["omnichannel.conversation"].with_context(
        active_test=False).search([])
    total = len(conversations)
    if not total:
        return
    _logger.info(
        "Backfilling the omnichannel history of %s conversations", total)
    history = env["omnichannel.history.service"]
    done = 0
    for index in range(0, total, BACKFILL_BATCH_SIZE):
        for conversation in conversations[index:index + BACKFILL_BATCH_SIZE]:
            targets = conversation._history_targets()
            if targets:
                history.backfill(conversation, targets)
        done = min(index + BACKFILL_BATCH_SIZE, total)
        # A full backfill can touch every message in the database; dropping
        # the cache between passes keeps memory flat instead of proportional
        # to the history being copied.
        env.invalidate_all()
        _logger.info("Omnichannel history backfilled: %s/%s", done, total)


def post_init_hook(env):
    """Catch up the history of a database that predates the feature.

    Odoo runs this on install only, which covers a fresh install onto an
    existing database. The matching upgrade path is
    ``migrations/18.0.1.1.0/post-migrate.py``, which calls the same function.
    """
    backfill_existing_history(env)
