"""neura-adapters — the ONLY package where a commerce platform name may appear.

A CI check greps the whole repository for platform names (`bagisto`, `shopify`,
`woocommerce`, `magento`, ...) and fails if any appears outside this package and
docs/. It is the single most important check in the repository: if it fails, the
platform-independence claim that the product is built on is no longer true.

Contents:

* ``generic/`` -- Tier 2, the MVP path. Implements ``CommerceAdapter`` against
  the published Generic Commerce Interface: nine read endpoints plus a signed
  webhook contract that any store can implement in an afternoon. This is what
  makes custom and newly-built stores integrate without us writing anything.
* ``shopify/``, ``woocommerce/`` -- Tier 1 native adapters, Phase 2+.
* ``feed/`` -- Tier 3 push/upload mode, Phase 3.

Adding a platform is one file plus a registry entry. If a new platform ever
requires a change outside this package, that is a design defect — raise it rather
than working around it.
"""

from neura_adapters.generic import GenericAdapter

__all__ = ["GenericAdapter"]
