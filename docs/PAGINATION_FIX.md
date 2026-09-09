# Pagination repair and optional infinite scrolling — 2026.09.08.5

Release .3 restored Pinterest search after the HTTP 403 compatibility repair, and the operator confirmed that release working on the VPS. Its result parser could still discard the continuation token, leaving a populated gallery without a Next page link. Release .4 corrected the cursor field and added optional automatic loading. The VPS then showed first-page images but no valid continuation; .5 repairs a remaining size limit defect.

## Continuation parsing

The earlier parser looked for continuation metadata under `resource_response`. The canonical response stores it at `resource.options.bookmarks[0]`, outside that object. The [gallery-dl Pinterest extractor](https://github.com/mikf/gallery-dl/blob/master/gallery_dl/extractor/pinterest.py) uses this response structure for pagination.

The parser now reads the canonical token first. Explicit empty, terminal or malformed values end pagination; they cannot be overridden by a token from an older response shape. Legacy singular bookmark fields and named bookmark lists remain supported when the canonical field is absent. Tokens must be nonempty strings of at most 4096 bytes without whitespace or control characters. Known end markers and an immediate repeat of the requested token are not offered as a next page.

Parsed search-cache keys now use a `v3:` prefix before hashing the query/bookmark tuple. This prevents entries produced by the previous parser from hiding the corrected continuation link. Cache size, expiry and request limits remain in effect.

The [HTTP 403 repair from .3](PINTEREST_403_FIX.md) remains part of this release. Correct continuation parsing does not make an unavailable provider available.

## Browsing behavior

Manual pages remain the default. Search, themes, gallery choices, quality settings and Next page links work without JavaScript. Selecting **Infinite scroll** in the **Browsing** preference adds `scroll=infinite` to the URL and enables the local script when another result page is available. The script requests the same server-rendered next page that the ordinary link opens.

- One next-page request runs at a time, with a 15-second deadline and a 2 MiB HTML response limit.
- Requests must stay on the same origin and search endpoint, with the same query and preferences. Redirects are rejected.
- Returned cards are rebuilt from validated image URLs and text. Arbitrary fetched markup and scripts are not inserted into the active page.
- Images are deduplicated across pages. Repeated bookmarks stop automatic loading; a page with no new images also stops automatic requests.
- **Pause auto-loading** stops automatic browsing. Errors do not trigger a retry loop: **Retry loading** or the ordinary **Next page** link gives the user control over the next attempt.
- Missing browser capabilities leave the ordinary navigation usable. There is no fixed page-count ceiling; Pinterest's continuation, end markers and repeated responses determine how far a search can proceed.

Cards already loaded remain in the document, and the sets used to detect duplicates and repeated bookmarks grow with the session. Deferring offscreen rendering helps layout work, but does not remove the cards or bound browser memory. Manual pages can be preferable for a long session on a memory-constrained device.

Nginx serves the exact `/static/infinite-scroll.js` asset. Both application and Nginx CSP allow `script-src 'self'` and `connect-src 'self'`; inline scripts and third-party scripts remain prohibited. The script talks to the local application, while the server continues to contact Pinterest and proxy images.

## Deployment verification

The updater checks the exact release health response, homepage, stylesheet and local script before live search checks. Its normal candidate test searches for `architecture`, requires image results and a usable Next page link, follows that link, and requires distinct new images on the second page. A missing link, failed page or repeated-only second page prevents cutover. The existing production container remains active during these checks.

The explicit `--skip-upstream-check` option skips both live pages, while retaining all local checks. It is an operator opt-out from verifying provider availability and pagination, not a correction for a failed page.

Local regression results and their exact scope are recorded in [AUDIT.md](../AUDIT.md) and [TEST_RESULTS.txt](TEST_RESULTS.txt). The development environment cannot run this release in Docker, contact Pinterest for live pagination, or verify scrolling in a real browser. The operator built .4 and supplied its failed pagination gate; no .5 VPS deployment was executed while preparing this package. Those checks must run in an environment with the required access; a local parser or script test does not substitute for them.

## Resumo em português

A .3 voltou a buscar imagens, mas podia perder o marcador da página seguinte ao procurar no local errado da resposta. A .4 passou a ler `resource.options.bookmarks[0]`, mas ainda rejeitava marcadores maiores que 2048 bytes. A .5 aceita até 4096 bytes e usa cache v3. Um marcador público válido de 2064 bytes demonstrou esse defeito; o tamanho do marcador recebido na sua VPS ainda não foi observado.

A paginação manual permanece como padrão e funciona sem JavaScript. A opção **Infinite scroll** carrega outras páginas conforme a navegação, com pausa, tentativa manual após erros e o link **Next page** como alternativa. Não há um teto artificial de páginas, mas o Pinterest pode encerrar ou repetir os resultados; os cartões já carregados continuam ocupando memória do navegador.

Antes da troca na VPS, o comando normal exige a primeira página de `architecture`, uma continuação válida e novas imagens na segunda página. A compilação Docker da .5, a paginação real e a verificação no navegador ainda dependem de execução em um ambiente com esse acesso.

## Cursor-size evidence and .5

A [published raw Pinterest response](https://github.com/Greenstorm5417/Zoeken/blob/ad718198797b7121ae0b3a6e9c9fe05c3630917a/zoeken/zoeken-engines/fixtures/generic/pinterest.json) contains an identical canonical/legacy cursor of 2064 ASCII bytes and 18 result rows. It is neither empty, terminal nor malformed. Release .4 would reject it solely because of its 2048-byte bound. This proves a compatibility defect, but does not establish the length of the cursor returned in the user's particular VPS failure. Regression fixtures reproduce its length without redistributing the third-party response.

Release .5 uses a shared PHP 4096-byte constant and the same browser bound. Cache v3 excludes .4 entries whose valid cursor was discarded. Nginx accepts request lines up to 16 KiB, enough for a percent-encoded cursor and normal parameters; larger lines still fail. Outbound URLs may use up to 32 KiB only at the exact Pinterest search endpoint, accommodating JSON plus percent-encoding expansion. The default URL limit remains 16 KiB and image URLs remain limited to 4 KiB.

If the .5 gate still fails, run `python3 deploy/diagnose_pagination.py` on the VPS from the .5 source directory. It reuses the exact .4 image from the reported build in one temporary candidate, reads first-page cursor types/lengths/rejection categories and tries one safe raw continuation up to 4096 bytes. No raw cursor, image URL, upstream body or environment is printed. It uses the deployment lock, removes only its own candidate and preserves the production container. The previous extracted .4 release and image must still exist.
