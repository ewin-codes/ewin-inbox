/** @odoo-module **/

/**
 * The signature a reply opens with, shared by everything that writes into
 * the composer.
 *
 * The composer shows it below an empty first line, the way a mail client
 * does, and the operator writes above it. Anything inserted for them — a
 * quick reply — goes above it too, so the signature stays where it signs.
 */

/**
 * The block the composer appends below the operator's words: two line
 * breaks and the signature, or nothing — for a channel without one, and for
 * an internal note, which nobody outside reads.
 */
export function signatureBlock(data) {
    if (data.composer_is_internal || !data.composer_signature) {
        return "";
    }
    return `\n\n${data.composer_signature}`;
}

/**
 * Where the operator's own words end: right above the signature while the
 * text still ends with it, the end of the text once they have changed it.
 */
export function replyEnd(text, block) {
    return block && text.endsWith(block) ? text.length - block.length : text.length;
}

/** `text` with `insertion` added as a new line at the end of the reply. */
export function insertIntoReply(text, block, insertion) {
    const end = replyEnd(text, block);
    const head = text.slice(0, end);
    return (head ? `${head}\n` : "") + insertion + text.slice(end);
}
