/**
 * Explaining `[EMAIL_1]` to the person who owns the data behind it.
 *
 * Both Review and Conversations render text **as the guard left it**: the
 * shopper's words are stored tokenised so that a transcript kept under a
 * merchant's retention policy does not become a long-term store of card numbers
 * (security-model.md §6.2), and the rehydrated text existed only in the reply
 * the shopper actually saw.
 *
 * Unexplained, that reads as a bug — a merchant looking for the address an order
 * was going to, finding `[ADDRESS_1]`, concludes the product lost it. So the note
 * appears exactly when a token does, and says what happened rather than
 * apologising for it.
 *
 * **`docs/console.md §3.3` promises this merchant unredacted PII and the storage
 * does not deliver it.** That is written up in the design doc as an open
 * decision. This component is what is true today; it is not the resolution.
 */

/** `[EMAIL_1]`, `[ADDRESS_2]`, `[CARD_1]` — the guard's placeholder shape. */
const PII_TOKEN = /\[[A-Z_]+_\d+\]/;

export function hasToken(...texts: string[]): boolean {
  return texts.some((text) => PII_TOKEN.test(text ?? ""));
}

export function TokenNote({ className = "" }: { className?: string }) {
  return (
    <p className={`text-xs text-muted-foreground ${className}`}>
      Text like <code className="text-foreground">[EMAIL_1]</code> is a personal detail the guard
      replaced before the model saw it. The same detail always gets the same label within a
      conversation. The real value was never stored here.
    </p>
  );
}
