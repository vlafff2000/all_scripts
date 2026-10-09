import { createRoot } from 'react-dom/client'
import '@fontsource/pt-sans/cyrillic-400.css'
import '@fontsource/pt-sans/cyrillic-700.css'
import '@fontsource/pt-sans/latin-400.css'
import '@fontsource/pt-sans/latin-700.css'
import './prefs'
import App from './App'
import '../../../pxg_core/web-ui/base.css'
import './styles.css'

createRoot(document.getElementById('root')!).render(<App />)
