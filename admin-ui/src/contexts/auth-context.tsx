import { createContext, useContext, useState, useCallback, useEffect, type ReactNode } from 'react'
import { setLogoutCallback } from '@/lib/api-client'

interface AuthContextType {
  isAuthenticated: boolean
  apiKey: string | null
  login: (key: string) => void
  logout: () => void
}

const AuthContext = createContext<AuthContextType | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [apiKey, setApiKey] = useState<string | null>(() =>
    sessionStorage.getItem('admin_api_key')
  )

  const logout = useCallback(() => {
    sessionStorage.removeItem('admin_api_key')
    setApiKey(null)
  }, [])

  const login = useCallback((key: string) => {
    sessionStorage.setItem('admin_api_key', key)
    setApiKey(key)
  }, [])

  useEffect(() => {
    setLogoutCallback(logout)
  }, [logout])

  return (
    <AuthContext.Provider value={{ isAuthenticated: !!apiKey, apiKey, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
