"use strict";

const readline = require("node:readline");
const { JSDOM, VirtualConsole } = require("jsdom");
const { Readability } = require("@mozilla/readability");
const TurndownService = require("turndown");
const { gfm } = require("turndown-plugin-gfm");

function extract(request) {
  if (!request || typeof request.html !== "string" || typeof request.url !== "string") {
    throw new TypeError("Expected {html: string, url: string}");
  }
  let url;
  try {
    url = new URL(request.url).href;
  } catch {
    url = "about:blank";
  }
  const dom = new JSDOM(request.html, {
    url,
    virtualConsole: new VirtualConsole(),
  });
  try {
    const article = new Readability(dom.window.document, {
      disableJSONLD: true,
      keepClasses: true,
    }).parse();
    if (!article || !article.textContent.trim()) {
      return { status: "no_output" };
    }
    const turndown = new TurndownService({
      headingStyle: "atx",
      codeBlockStyle: "fenced",
      bulletListMarker: "-",
    });
    let complexTables = 0;
    turndown.use(gfm);
    turndown.addRule("complexTables", {
      filter(node) {
        return node.nodeName === "TABLE" && Boolean(node.querySelector("[rowspan], [colspan]"));
      },
      replacement(content, node) {
        complexTables += 1;
        return `\n\n${node.outerHTML}\n\n`;
      },
    });
    return {
      status: "ok",
      html: article.content,
      text: article.textContent.trim(),
      markdown: turndown.turndown(article.content),
      metadata: {
        title: article.title,
        byline: article.byline,
        excerpt: article.excerpt,
        siteName: article.siteName,
        lang: article.lang,
        dir: article.dir,
        publishedTime: article.publishedTime,
      },
      diagnostics: {
        configuration: "offline-v1",
        versions: require("./package.json").dependencies,
        complex_tables_preserved_as_html: complexTables,
      },
    };
  } finally {
    dom.window.close();
  }
}

const lines = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
lines.on("line", (line) => {
  let result;
  try {
    result = extract(JSON.parse(line));
  } catch (error) {
    result = { status: "error", diagnostics: { error: String(error.message || error) } };
  }
  process.stdout.write(`${JSON.stringify(result)}\n`);
});
