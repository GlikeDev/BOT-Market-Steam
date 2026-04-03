import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'

const embeddedRoot = document.getElementById('react-inv-root');
const standaloneRoot = document.getElementById('root');

if (embeddedRoot) {
  createRoot(embeddedRoot).render(
    <StrictMode>
      <App embedded={true} />
    </StrictMode>,
  );
} else if (standaloneRoot) {
  createRoot(standaloneRoot).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}
