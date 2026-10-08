import { createRouter, createWebHistory } from 'vue-router'
import Home from '../views/Home.vue'

const routes = [
  { path: '/', name: 'Home', component: Home },
  { path: '/chat', name: 'Chat', component: () => import('../views/Chat.vue') },
  { path: '/search', name: 'Search', component: () => import('../views/Search.vue') },
  { path: '/news', name: 'News', component: () => import('../views/News.vue') },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
