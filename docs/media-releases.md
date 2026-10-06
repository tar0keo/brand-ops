# Media releases

The Media releases tab keeps a list of links to articles and posts, each matched to a brand.

## Adding links
Paste one or more links (up to 20 at a time) and click Add links. For each one the app reads the page on your computer, then scores every active brand from several kinds of evidence:

| Evidence | Weight |
|---|---|
| The brand's name in the headline | Strongest |
| A website that is the brand's: one you added on the Brands tab, or one named like the brand | Strong |
| The brand's name in the page text | Medium |
| The brand's name in the wording of the link | Medium |
| The article linking to the brand's website | Light |

**Names are matched however they are written.** "Brand 30", "Brand30", "BRAND-30", and "brand_30" are all the same name, and so is a run-together form like "AcmeLending" for "Acme Lending". Numbers are kept whole, so "Brand 30" is never confused with "Brand 3" or "Brand 300". Very short names (three letters or fewer, such as FLA) must match capital letters exactly.

**Websites are matched by their name too.** For a brand called "Brand 30", the sites `brand30.com`, `www.brand-30.net`, `getbrand30.com`, `brand30loans.com`, and `mybrand30.co.uk` all count, with no need to add each one. The ending of the address doesn't matter. A site that looks nothing like the brand's name still needs to be added on the Brands tab.

A brand is assigned automatically only when it clearly stands out (a score of at least 2, ahead of every other brand). Otherwise the link stays Unassigned and shows "Possible: ..." so you can pick the brand yourself. Each automatic match lists the reasons for it, for example "name in the headline, its website address".

## Changing a match
Click the Brand box on a row and start typing: the list narrows as you type, and you don't need to match spaces or capitals ("brand30" finds Brand 30). Clear the box to unassign. A match you set yourself is never overwritten.

**Re-check automatic matches** runs the detection again over every link whose brand the app chose, assigned or not. Use it after adding a brand or a website, or after an update that improves matching. It reports how many links were newly matched and how many changed.

## Limits
- **Some pages can't be read.** Posts on social sites often need a login, some sites block automatic reading, and PDFs have no text. Those links are still saved, labelled as unreadable, and matched from the link and website name only, which is why a clear website address matters.
- **Names that are everyday words** can match by accident ("Summit", "Capital"). Check matches for brands with common names.
- **Only public web addresses are fetched.** Links to private networks, other ports, or addresses with logins are refused, including after redirects.
- In demo mode, links are kept in memory only and disappear when the demo ends.

## Summaries
When a link is added, the app writes a short summary from the page's own text: up to three sentences that echo the headline, come early in the article, name the brand it was matched to, and carry facts such as numbers. Navigation, cookie, and subscription text is skipped. The summary appears under the headline on the Media releases tab.

These summaries are extracted, not written by an AI, so they quote the article rather than paraphrase it, and an article with little text gives a thin summary. Links that could not be read have no summary. **Re-check automatic matches** also writes summaries for older links that never had one.

## In Jira tickets
When a ticket is created (or exported to CSV), the recent coverage of its brand is added to the ticket text under "Related media coverage": the headline as a link, the source and date, and the summary. It is added only to the kinds of ticket where press coverage is useful context (review rating, negative reviews, reply rate, and falling AI citations), only for links assigned to that brand in the last 90 days, at most 5, newest first. Links the app could not read are left out unless you assigned them yourself. Change these under `media_context` in `config/task_rules.yaml`.

The Actions tab shows, under each such task, the coverage that will go into the ticket, so you can check it before creating anything. Coverage is added when a ticket is created; articles saved afterwards are not added to tickets that already exist.

## Demo mode
The demo starts with about fifteen sample articles: some tell the same story as a brand's scorecard (so the matching Jira tasks show attached coverage), some mention no brand and stay unassigned, and one cannot be read and is matched from its website alone.
