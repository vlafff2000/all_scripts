import { createRoot } from 'react-dom/client'
import '../../../pxg_core/web-ui/desktopDownload'
import '@fontsource/pt-sans/cyrillic-400.css'
import '@fontsource/pt-sans/cyrillic-700.css'
import '@fontsource/pt-sans/latin-400.css'
import '@fontsource/pt-sans/latin-700.css'
import { mountLogButton } from '../../../pxg_core/web-ui/LogButton'
import App from './App'
import '../../../pxg_core/web-ui/base.css'
import '../../../pxg_core/web-ui/logbutton.css'
import './ocr.css'

createRoot(document.getElementById('root')!).render(<App />)
mountLogButton()
