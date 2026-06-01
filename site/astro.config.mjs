// @ts-check
import { defineConfig } from "astro/config";
import react from "@astrojs/react";
import tailwindcss from "@tailwindcss/vite";

// Static site (GitHub Pages). Pages consume the JSON produced by /build.
// Project Pages live at user.github.io/pegada-publica, so `site` is the GitHub
// Pages origin and `base` is the repo path. Internal links go through BASE_URL.
export default defineConfig({
  site: "https://martjoao.github.io",
  base: "/pegada-publica",
  integrations: [react()],
  vite: { plugins: [tailwindcss()] },
});
