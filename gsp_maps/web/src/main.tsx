import { createRoot } from 'react-dom/client'
import '@fontsource/pt-sans/cyrillic-400.css'
import '@fontsource/pt-sans/cyrillic-700.css'
import '@fontsource/pt-sans/latin-400.css'
import '@fontsource/pt-sans/latin-700.css'
import './prefs'
import App from './App'
import './styles.css'
import './app.css'

createRoot(document.getElementById('root')!).render(<App />)
