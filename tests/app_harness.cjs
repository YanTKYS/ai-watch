// 実app.jsを実行する小さなDOM/通信/タイマー。実ブラウザ確認と併用する。
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const walk = node => [node, ...node.childNodes.flatMap(walk)];

function harness(search = '') {
  const nodes = {}, requests = [], timers = new Map(), announcements = [];
  let timerId = 0;
  const document = {};
  class Element {
    constructor(tag, text = '') {
      this.tag = tag; this.text = text; this.childNodes = []; this.listeners = {}; this.attributes = {};
      this._hidden = false; this.disabled = false; this.selectedValue = null;
    }
    set textContent(value) {
      this.text = String(value); this.childNodes = [];
      if (this === nodes['view-announcement']) announcements.push(this.text);
    }
    get textContent() { return this.text + this.childNodes.map(n => n.textContent).join(''); }
    get firstChild() { return this.childNodes[0] ?? null; }
    get hidden() { return this._hidden; }
    set hidden(value) {
      this._hidden = value;
      if (value && walk(this).includes(document.activeElement)) document.activeElement = document.body;
    }
    get options() { return this.childNodes; }
    get value() { return this.selectedValue ?? (this.tag === 'select' ? this.options[0]?.value ?? '' : ''); }
    set value(value) { this.selectedValue = value; }
    appendChild(node) {
      this.childNodes.push(...(node.tag === '#fragment' ? node.childNodes : [node]));
      return node;
    }
    replaceChildren(...children) {
      if (walk(this).slice(1).includes(document.activeElement)) document.activeElement = document.body;
      this.childNodes = []; children.forEach(n => this.appendChild(n));
    }
    setAttribute(key, value) { this.attributes[key] = String(value); }
    getAttribute(key) { return this.attributes[key]; }
    addEventListener(name, fn) { (this.listeners[name] ??= []).push(fn); }
    emit(name, event = {}) { for (const fn of this.listeners[name] ?? []) fn(event); }
    focus() { document.activeElement = this; }
  }
  Object.assign(document, {
    body: new Element('body'),
    getElementById(id) {
      if (id === 'view-heading') return nodes.content && walk(nodes.content).find(n => n.id === id) || null;
      return nodes[id] ??= new Element(id.endsWith('-select') ? 'select' : 'div');
    },
    createElement: tag => new Element(tag), createTextNode: text => new Element('#text', text),
    createDocumentFragment: () => new Element('#fragment'),
  });
  document.activeElement = document.body;
  const context = vm.createContext({
    URL, URLSearchParams, location: { search }, document,
    setTimeout: fn => { timers.set(++timerId, fn); return timerId; },
    clearTimeout: id => timers.delete(id),
    fetch: url => new Promise((resolve, reject) => requests.push({ url, resolve, reject })),
  });
  const root = path.join(__dirname, '..');
  vm.runInContext(fs.readFileSync(path.join(root, 'parser.js'), 'utf8') + '\n' +
                  fs.readFileSync(path.join(root, 'app.js'), 'utf8'), context);
  return {
    nodes, requests, document, announcements, timers, get: expression => vm.runInContext(expression, context),
    flushTimers() { const pending = [...timers.values()]; timers.clear(); pending.forEach(fn => fn()); },
    respond(i, text, ok = true) { requests[i].resolve({ ok, status: ok ? 200 : 503, text: async () => text }); },
    fail(i) { requests[i].reject(new Error('offline')); },
    search(query) { nodes['search-input'].value = query; nodes['search-input'].emit('keydown', { key: 'Enter' }); },
    input(query, event = {}) { nodes['search-input'].value = query; nodes['search-input'].emit('input', event); },
    retry() { nodes['load-retry'].emit('click'); },
  };
}
const settle = () => new Promise(resolve => setImmediate(resolve));
const log = (title = 'Daily', ym = '2026-10') => `# Month\n## ${ym}-02\n### Coding\n#### ${title}\n- URL: https://a.example/${title}\n`;
const entries = Array.from({ length: 120 }, (_, i) => ({ title: `Alpha ${i}`, url: `https://a.example/${i}` }));
async function ready(search = '') {
  const h = harness(search);
  h.respond(0, '["2026-10","2026-09"]'); await settle();
  h.respond(1, log()); await settle();
  return h;
}
module.exports = { harness, settle, log, entries, ready, walk };
