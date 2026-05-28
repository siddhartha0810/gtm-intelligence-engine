export interface User {
  id: number
  name: string
  email: string
  role: 'owner' | 'admin' | 'viewer' | 'recruitment'
}
