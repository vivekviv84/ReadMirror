'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { motion } from 'framer-motion'
import Link from 'next/link'
import { Loader2, Sparkles, MessageSquare, Brain, FileText, Mail, Lock, Eye, EyeOff } from 'lucide-react'
import { Logo } from '@/components/logo'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { toast } from 'sonner'
import { authAPI } from '@/lib/api'
import { useAuth } from '@/contexts/auth-context'

const features = [
  {
    icon: FileText,
    title: 'Upload & Understand',
    desc: 'Drop any PDF or paste a URL — get instant structured summaries.',
  },
  {
    icon: MessageSquare,
    title: 'Chat With Your Material',
    desc: 'Ask questions and get answers grounded in your actual content.',
  },
  {
    icon: Brain,
    title: 'Test Your Knowledge',
    desc: 'Auto-generated MCQ and True/False quizzes at any difficulty.',
  },
  {
    icon: Sparkles,
    title: 'Powered by AI',
    desc: '20 daily AI generations (summary + quiz) with unlimited material chat.',
  },
]

export default function HomePage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const { user, isLoading: isAuthLoading, logout, login } = useAuth()
  const router = useRouter()

  const handleEmailSignIn = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!email || !password) {
      toast.error('Please enter both email and password')
      return
    }
    setIsSubmitting(true)
    setErrorMessage(null)
    try {
      const result = await authAPI.login(email.trim(), password)
      login(result.user, result.access_token)
      toast.success('Signed in successfully!')
      router.replace('/dashboard')
    } catch (err: any) {
      toast.error(err?.message || 'Sign in failed. Please try again.')
    } finally {
      setIsSubmitting(false)
    }
  }

  useEffect(() => {
    const searchParams = new URLSearchParams(window.location.search)
    const hashParams = new URLSearchParams(window.location.hash.replace('#', '?'))
    const rawError =
      searchParams.get('error_description') ||
      hashParams.get('error_description') ||
      searchParams.get('error') ||
      hashParams.get('error')

    if (rawError) {
      if (user) {
        logout()
      }
      const decoded = decodeURIComponent(rawError.replace(/\+/g, ' '))
      setErrorMessage(decoded)
      try {
        window.history.replaceState({}, document.title, window.location.pathname)
      } catch {}
      return
    }

    if (!isAuthLoading && user) {
      router.replace('/dashboard')
    }
  }, [user, isAuthLoading, router, logout])

  if (isAuthLoading || (user && !errorMessage)) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <Loader2 className="w-8 h-8 animate-spin text-primary" />
      </div>
    )
  }

  return (
    <div className="min-h-screen flex bg-background">

      {/* ── Left panel ── */}
      <div className="hidden lg:flex flex-col justify-between w-[55%] bg-primary/5 border-r border-border/50 px-14 py-12">
        {/* Logo */}
        <Logo />

        {/* Hero text */}
        <div className="space-y-10">
          <motion.div
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6 }}
          >
            <h1 className="text-4xl font-bold text-foreground leading-tight mb-4">
              Your AI-powered<br />study companion
            </h1>
            <p className="text-muted-foreground text-lg leading-relaxed max-w-md">
              Upload your materials, chat with them, generate quizzes, and get summaries — all in one place.
            </p>
          </motion.div>

          {/* Feature list */}
          <div className="grid grid-cols-1 gap-4">
            {features.map((f, i) => (
              <motion.div
                key={f.title}
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.5, delay: 0.15 + i * 0.1 }}
                className="flex items-start gap-4 p-4 rounded-xl bg-card/60 border border-border/40"
              >
                <div className="w-9 h-9 rounded-lg bg-primary/10 flex items-center justify-center flex-shrink-0 mt-0.5">
                  <f.icon className="w-4 h-4 text-primary" />
                </div>
                <div>
                  <p className="font-semibold text-foreground text-sm">{f.title}</p>
                  <p className="text-muted-foreground text-sm mt-0.5 leading-relaxed">{f.desc}</p>
                </div>
              </motion.div>
            ))}
          </div>
        </div>

        {/* Bottom quote */}
        <p className="text-xs text-muted-foreground/60">
          Study smarter, not harder.
        </p>
      </div>

      {/* ── Right panel ── */}
      <div className="flex-1 flex flex-col items-center justify-center px-6 py-12">
        {/* Mobile logo */}
        <div className="mb-10 w-full max-w-sm lg:hidden">
          <Logo />
        </div>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.1 }}
          className="w-full max-w-sm space-y-8"
        >

          {/* Heading */}
          <div className="space-y-1.5 pt-1">
            <h2 className="text-2xl font-bold text-foreground">Welcome back</h2>
            <p className="text-muted-foreground text-sm">
              Sign in to continue your learning journey
            </p>
          </div>

          {errorMessage && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900/60 dark:bg-red-950/40 dark:text-red-200">
              {errorMessage}
            </div>
          )}

          {/* Sign in form & OAuth */}
          <div className="space-y-5">
            <form onSubmit={handleEmailSignIn} className="space-y-3.5">
              <div className="space-y-1.5">
                <Label htmlFor="email" className="text-xs font-medium text-muted-foreground">
                  Email address
                </Label>
                <div className="relative">
                  <Mail className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input
                    id="email"
                    type="email"
                    placeholder="Email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="pl-9 h-11 bg-card/50 border-border/60 focus-visible:ring-primary"
                    required
                  />
                </div>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="password" className="text-xs font-medium text-muted-foreground">
                  Password
                </Label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input
                    id="password"
                    type={showPassword ? 'text' : 'password'}
                    placeholder="Password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="pl-9 pr-10 h-11 bg-card/50 border-border/60 focus-visible:ring-primary"
                    required
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors p-1"
                  >
                    {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
              </div>

              <Button
                type="submit"
                disabled={isSubmitting || isAuthLoading}
                className="w-full h-11 text-sm font-semibold shadow-md transition-all"
              >
                {isSubmitting ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Signing in...
                  </>
                ) : (
                  'Sign In'
                )}
              </Button>

              <div className="flex items-center justify-between text-xs pt-1 gap-4">
                <span className="text-muted-foreground shrink-0">
                  Don&apos;t have an account?
                  <Link href="/signup" className="ml-1.5 font-semibold text-primary hover:underline">
                    Sign up
                  </Link>
                </span>
              </div>
            </form>
          </div>

          {/* Stats row */}
          <div className="grid grid-cols-3 gap-3 pt-4  mt-6 border-t border-border/40">
            {[
              { value: '20', label: 'Daily generations' },
              { value: 'Free', label: 'to get started' },
              { value: '∞', label: 'Chat messages' },
            ].map((stat) => (
              <div key={stat.label} className="text-center space-y-1">
                <p className={`font-bold text-primary ${stat.value === '∞' ? 'text-xl leading-none -mb-0.5' : 'text-sm'}`}>
                  {stat.value}
                </p>
                <p className="text-xs text-muted-foreground">{stat.label}</p>
              </div>
            ))}
          </div>
        </motion.div>
      </div>
    </div>
  )
}
