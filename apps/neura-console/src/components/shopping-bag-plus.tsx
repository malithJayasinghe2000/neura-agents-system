/**
 * A shopping bag with a plus: *Shoppers asked for*'s menu icon (board 67).
 * Lucide has the bag but not this one, so it is drawn from Lucide's own bag,
 * and behaves as every other menu icon does.
 */
import { createLucideIcon } from "lucide-react";

export const ShoppingBagPlus = createLucideIcon("shopping-bag-plus", [
  ["path", { d: "M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z", key: "bag" }],
  ["path", { d: "M3 6h18", key: "rim" }],
  ["path", { d: "M12 10v6", key: "down" }],
  ["path", { d: "M9 13h6", key: "across" }],
]);
