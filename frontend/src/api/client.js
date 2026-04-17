import axios from 'axios'

const api = axios.create({ baseURL: '/api', timeout: 120000 })

api.interceptors.response.use(
  res => res.data,
  err => {
    const msg = err.response?.data?.detail || err.message || 'Network error'
    return Promise.reject(new Error(msg))
  }
)

export const health           = ()          => api.get('/health')
export const runOrchestratorSync = ()       => api.get('/orchestrator/run-sync')
export const triggerOrchestrator = ()       => api.post('/orchestrator/run')
export const getOrchestratorOutput = ()     => api.get('/orchestrator/output')
export const getSystemStatus  = ()          => api.get('/orchestrator/status')
export const getCommandCenter = ()          => api.get('/command-center')
export const getPlants        = ()          => api.get('/plants')
export const getDemand        = ()          => api.get('/demand')
export const getInventory     = ()          => api.get('/inventory')
export const getProduction    = ()          => api.get('/production')
export const getMachines      = ()          => api.get('/machines')
export const getFinance       = ()          => api.get('/finance')
export const getCarbon        = ()          => api.get('/carbon')
export const getAgentLog      = (p={})      => api.get('/agents/log', { params: p })

export const getHitlCounts    = ()          => api.get('/hitl/counts')
export const getHitlPending   = (t)         => api.get('/hitl/pending', { params: t ? { item_type: t } : {} })
export const getHitlHistory   = (p={})      => api.get('/hitl/history', { params: p })
export const approveHitl      = (id, body)  => api.post(`/hitl/approve/${id}`, body)
export const rejectHitl       = (id, body)  => api.post(`/hitl/reject/${id}`, body)
export const enqueueHitl      = (body)      => api.post('/hitl/enqueue', body)

export const nlpQuery         = (body)      => api.post('/nlp/query', body)
export const getSimDefaults   = (plant)     => api.get(`/simulation/defaults/${encodeURIComponent(plant)}`)
export const runSimulation    = (body)      => api.post('/simulation/run', body)

export default api
