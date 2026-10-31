"use strict";
// A deliberately small Markdown reader. No HTML parsing, images, embeds or remote code.
const ImportMarkdown = (() => {
  function safeLink(value) {
    if (typeof value !== "string" || /[\s\u0000-\u001f\u007f]/.test(value)) return "";
    try {
      const u = new URL(value);
      return ["https:", "http:"].includes(u.protocol) && !u.username && !u.password ? u.href : "";
    } catch { return ""; }
  }
  function node(doc, tag, text) {
    const n = doc.createElement(tag);
    if (text !== undefined) n.textContent = text;
    return n;
  }
  function link(doc, label, value) {
    const url = safeLink(value);
    if (!url) return doc.createTextNode(label);
    const a = node(doc, "a", label);
    a.href = url; a.target = "_blank"; a.rel = "noopener noreferrer";
    a.title = "新しいタブで開く";
    return a;
  }
  function inline(doc, parent, text, depth = 0) {
    if (depth > 3) { parent.appendChild(doc.createTextNode(text)); return; }
    const tokens = /!?\[([^\]\n]*)\]\(([^()\s]*(?:\([^()\s]*\)[^()\s]*)*)\)|`([^`\n]+)`|\*\*([^*\n]+)\*\*|__([^_\n]+)__|\*([^*\n]+)\*|https?:\/\/[^\s<>]+/g;
    let last = 0, m;
    while ((m = tokens.exec(text))) {
      parent.appendChild(doc.createTextNode(text.slice(last, m.index)));
      if (m[1] !== undefined) {
        // Images remain text; never create an img or fetch a Markdown resource.
        parent.appendChild(m[0].startsWith("!") ? doc.createTextNode(m[1]) : link(doc, m[1], m[2]));
      } else if (m[3] !== undefined) parent.appendChild(node(doc, "code", m[3]));
      else if (m[4] !== undefined || m[5] !== undefined || m[6] !== undefined) {
        const n = node(doc, m[6] !== undefined ? "em" : "strong");
        inline(doc, n, m[4] ?? m[5] ?? m[6], depth + 1); parent.appendChild(n);
      } else {
        const url = m[0].replace(/[.,;!?)、。]+$/, "");
        parent.appendChild(link(doc, url, url));
        parent.appendChild(doc.createTextNode(m[0].slice(url.length)));
      }
      last = tokens.lastIndex;
    }
    parent.appendChild(doc.createTextNode(text.slice(last)));
  }
  function cells(line) {
    const result = []; let cell = "", code = false;
    let text = line.trim().replace(/^\|/, "").replace(/(?<!\\)\|$/, "");
    for (let i = 0; i < text.length; i++) {
      if (text[i] === "\\" && text[i + 1] === "|") { cell += "|"; i++; }
      else if (text[i] === "`") { code = !code; cell += text[i]; }
      else if (text[i] === "|" && !code) { result.push(cell.trim()); cell = ""; }
      else cell += text[i];
    }
    result.push(cell.trim()); return result;
  }
  function blocks(markdown) {
    const lines = markdown.replace(/\r\n?/g, "\n").split("\n");
    const out = []; let i = 0;
    const special = line => /^(?:#{1,6}\s|\s*[-*+]\s|\s*\d+[.)]\s|```|~~~|>|\s*(?:---+|\*\*\*+)\s*$)/.test(line);
    while (i < lines.length) {
      const line = lines[i];
      if (!line.trim()) { i++; continue; }
      const fence = line.match(/^(`{3,}|~{3,})/);
      if (fence) {
        const code = []; i++;
        while (i < lines.length && !lines[i].startsWith(fence[1])) code.push(lines[i++]);
        if (i < lines.length) i++;
        out.push({ type: "code", text: code.join("\n") }); continue;
      }
      const heading = line.match(/^(#{1,6})\s+(.+?)\s*#*$/);
      if (heading) { out.push({ type: "heading", level: heading[1].length, text: heading[2] }); i++; continue; }
      if (/^\s*(?:---+|\*\*\*+)\s*$/.test(line)) { out.push({ type: "hr" }); i++; continue; }
      if (i + 1 < lines.length && line.includes("|") && cells(lines[i + 1]).every(c => /^:?-{3,}:?$/.test(c))) {
        const rows = [cells(line)]; i += 2;
        while (i < lines.length && lines[i].includes("|") && lines[i].trim()) rows.push(cells(lines[i++]));
        out.push({ type: "table", rows }); continue;
      }
      const list = line.match(/^\s*(?:([-*+])|(\d+)[.)])\s+(.+)$/);
      if (list) {
        const ordered = Boolean(list[2]), items = [];
        while (i < lines.length) {
          const m = lines[i].match(/^\s*(?:([-*+])|(\d+)[.)])\s+(.+)$/);
          if (!m || Boolean(m[2]) !== ordered) break;
          items.push(m[3]); i++;
        }
        out.push({ type: ordered ? "ol" : "ul", items }); continue;
      }
      const paragraph = [line]; i++;
      while (i < lines.length && lines[i].trim() && !special(lines[i])
          && !(i + 1 < lines.length && lines[i].includes("|") && cells(lines[i + 1]).every(c => /^:?-{3,}:?$/.test(c)))) paragraph.push(lines[i++]);
      out.push({ type: "paragraph", text: paragraph.join("\n") });
    }
    return out;
  }
  function render(doc, markdown, baseHeading = 3) {
    const fragment = doc.createDocumentFragment(); let previous = baseHeading - 1;
    for (const b of blocks(markdown)) {
      let n;
      if (b.type === "heading") {
        const level = Math.min(6, baseHeading + b.level - 1, previous + 1);
        previous = level; n = node(doc, "h" + level); inline(doc, n, b.text);
      } else if (b.type === "table") {
        n = node(doc, "div"); n.className = "import-table"; n.tabIndex = 0;
        n.setAttribute("role", "region"); n.setAttribute("aria-label", "レポートの表（横にスクロールできます）");
        const table = node(doc, "table"), head = node(doc, "thead"), body = node(doc, "tbody");
        b.rows.forEach((row, i) => {
          const tr = node(doc, "tr");
          row.forEach(text => { const td = node(doc, i ? "td" : "th"); if (!i) td.scope = "col"; inline(doc, td, text); tr.appendChild(td); });
          (i ? body : head).appendChild(tr);
        });
        table.appendChild(head); table.appendChild(body); n.appendChild(table);
      } else if (["ul", "ol"].includes(b.type)) {
        n = node(doc, b.type); for (const text of b.items) { const li = node(doc, "li"); inline(doc, li, text); n.appendChild(li); }
      } else if (b.type === "code") { n = node(doc, "pre"); n.appendChild(node(doc, "code", b.text)); }
      else if (b.type === "hr") n = node(doc, "hr");
      else { n = node(doc, "p"); inline(doc, n, b.text); }
      fragment.appendChild(n);
    }
    return fragment;
  }
  function grok(markdown) {
    const lines = markdown.replace(/\r\n?/g, "\n").split("\n");
    let title = "", current = null, last = "";
    const meta = Object.create(null), items = [];
    for (const line of lines) {
      if (line.startsWith("# ")) { title = line.slice(2).trim(); continue; }
      if (line.startsWith("## ")) { current = { title: line.slice(3).trim(), fields: Object.create(null) }; items.push(current); last = ""; continue; }
      const m = line.match(/^[-*]\s+([^:：]+)[:：]\s*(.*)$/);
      if (m) { last = m[1].trim(); (current ? current.fields : meta)[last] = m[2]; }
      else if (line.trim() && last) { const fields = current ? current.fields : meta; fields[last] += "\n" + line.trim(); }
    }
    return { title, meta, items };
  }
  return { safeLink, link, inline, cells, blocks, render, grok };
})();
if (typeof module !== "undefined" && module.exports) module.exports = ImportMarkdown;
