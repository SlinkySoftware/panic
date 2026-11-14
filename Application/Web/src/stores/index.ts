import { defineStore } from '@quasar/app-vite';
import { createPinia } from 'pinia';

// Quasar wires this Pinia instance into the app, the router (`store` param) and boot files.
export default defineStore(() => createPinia());
