import { mount } from 'svelte'
import App from './App.svelte'
import './app.css'

// Suppress the native/browser context menu globally so custom menus work
document.addEventListener('contextmenu', (e) => {
  e.preventDefault()
})

const app = mount(App, {
  target: document.getElementById('app')!,
})

export default app
