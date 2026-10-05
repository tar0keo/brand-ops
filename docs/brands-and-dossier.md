# Categories, brands, and the dossier

## Categories

Brands are grouped by loan type (or level). Edit the list on the Brands tab, under Loan categories: add a category, rename it, reorder it with Up and Down, or remove it. Renaming is always safe, because the id stays the same. Removing a category moves its brands to Uncategorized, and research data stored under it is kept. The list is saved in `config/categories.yaml`, which you can also edit by hand. A brand with no valid category shows under "Uncategorized". Change a brand's category from the Brands tab.

The category selector in the header filters the summary at the top and every tab. With "All categories", each table is grouped by category: the group row shows that category's totals and the brands sit beneath it. Click a column heading to sort the brands within each group; click again to reverse.

## Managing brands and sites (Brands tab)

- **Add brand:** name and category. The id is made from the name (for example "Zeta Co" becomes `zeta_co`) and can't change later, because stored data is keyed on it.
- **Archive:** hides a brand from every view, total, and task, but keeps its data and config so it can be restored. There is no hard delete on purpose.
- **Sites:** add a domain to a brand (pasting a full URL is fine). A domain can belong to one brand only. Trustpilot reviews are matched to brands by these domains.
- Changes are saved to `config/brands.yaml`. The app rewrites that file, so comments added by hand are not kept.
- **Demo mode uses its own 30 sample brands (Brand 1 to Brand 30)** in a temporary file, so editing brands in a demo never touches your real `config/brands.yaml`. Restarting the demo resets them.

## Dossier

"Open dossier" in the header builds a standalone HTML report for the chosen period. It starts with portfolio totals, what stands out, and a table by category, then has one section per category (totals, brand scorecard, four charts, proposed actions), then data source status. If a category is selected in the header, the dossier covers only that category. "Download" saves it as a file; use your browser's Print, Save as PDF for a PDF. It contains no scripts and no network calls.

The "what stands out" notes come from simple rules, not AI.
