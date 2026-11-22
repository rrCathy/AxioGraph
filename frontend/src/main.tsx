import React from 'react'
import ReactDOM from 'react-dom/client'
import 'katex/dist/katex.min.css'
// Self-hosted variable fonts (bundled at build time — no runtime downloads):
// Inter covers Latin UI glyphs and JetBrains Mono covers numerals/code tags;
// CJK glyphs still fall through to the system stacks in index.css.
import '@fontsource-variable/inter'
import '@fontsource-variable/jetbrains-mono'
import './styles/tokens.css'
import App from './App'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
