import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { loadStationConfig } from './runtimeConfig'

void loadStationConfig().then(({ config, error }) => createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App config={config} configError={error} />
  </StrictMode>,
))
