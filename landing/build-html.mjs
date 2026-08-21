/**
 * Gera um HTML único e autocontido (CSS + JS inline) a partir do app React.
 * Saída: pokersync-landing.html — abre direto no navegador, sem servidor.
 *
 * O bundle é emitido em formato IIFE (script clássico, não módulo) porque
 * módulos ES são bloqueados por CORS quando a página roda em file://.
 */
import { build } from "vite";
import react from "@vitejs/plugin-react";
import { readFile, writeFile, rm } from "node:fs/promises";
import { readdir } from "node:fs/promises";
import path from "node:path";

const OUT_DIR = path.resolve("dist-inline");
const TARGET = path.resolve("pokersync-landing.html");

await build({
  plugins: [react()],
  logLevel: "warn",
  build: {
    outDir: OUT_DIR,
    emptyOutDir: true,
    cssCodeSplit: false,
    assetsInlineLimit: 100_000_000, // fontes/imagens viram data URI
    rollupOptions: {
      output: {
        format: "iife",
        inlineDynamicImports: true,
        entryFileNames: "bundle.js",
        assetFileNames: "bundle[extname]",
      },
    },
  },
});

const files = await readdir(OUT_DIR);
const jsFile = files.find((f) => f.endsWith(".js"));
const cssFile = files.find((f) => f.endsWith(".css"));

const js = await readFile(path.join(OUT_DIR, jsFile), "utf8");
const css = await readFile(path.join(OUT_DIR, cssFile), "utf8");

const html = `<!doctype html>
<html lang="pt-BR" class="scroll-smooth">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta name="theme-color" content="#090d16" />
    <title>PokerSync — Sua rotina de poker, tudo integrado em uma só plataforma</title>
    <meta
      name="description"
      content="Abandone as 5 assinaturas separadas e as planilhas quebradas. Estude ranges, treine drills, revise mãos, gerencie sua banca e acompanhe seu time no único ecossistema 100% conectado."
    />
    <meta property="og:type" content="website" />
    <meta property="og:title" content="PokerSync — Um único ecossistema. Sem atrito. Da teoria ao lucro." />
    <meta property="og:description" content="Estude ranges, treine drills, revise mãos, gerencie sua banca e acompanhe seu time em uma só plataforma." />
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link
      href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap"
      rel="stylesheet"
    />
    <style>
${css}
    </style>
  </head>
  <body class="bg-abyss-900 antialiased">
    <div id="root"></div>
    <script>
${js}
    </script>
  </body>
</html>
`;

await writeFile(TARGET, html, "utf8");
await rm(OUT_DIR, { recursive: true, force: true });

const kb = (Buffer.byteLength(html) / 1024).toFixed(0);
console.log(`pokersync-landing.html gerado — ${kb} kB (CSS + JS inline)`);
