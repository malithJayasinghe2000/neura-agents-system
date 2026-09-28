"use client";

/**
 * Scrolls the open product's row into the list's view. The list scrolls on its
 * own on a wide screen, and an open product far down it — opened from a link,
 * or from a filter — would otherwise be highlighted where nobody can see it.
 */
import { useEffect } from "react";

export function KeepInView({ productId }: { productId: string }) {
  useEffect(() => {
    if (!productId) return;
    document
      .querySelector(`[data-product-list] [data-product="${CSS.escape(productId)}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [productId]);
  return null;
}
