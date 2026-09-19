'use client'

import { useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { AlertTriangle, RefreshCw, Home } from 'lucide-react'
import Link from 'next/link'

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    console.error('Application error:', error)
  }, [error])

  return (
    <div className="min-h-screen flex flex-col items-center justify-center gap-6 bg-background px-4">
      <div className="flex items-center justify-center w-16 h-16 rounded-full bg-destructive/10">
        <AlertTriangle className="h-8 w-8 text-destructive" />
      </div>
      <div className="text-center space-y-2">
        <h1 className="text-2xl font-bold">Something went wrong</h1>
        <p className="text-muted-foreground max-w-md">
          An unexpected error occurred. Please try again or return to the home page.
        </p>
      </div>
      <div className="flex gap-3">
        <Button variant="outline" asChild>
          <Link href="/">
            <Home className="mr-2 h-4 w-4" />
            Home
          </Link>
        </Button>
        <Button onClick={reset}>
          <RefreshCw className="mr-2 h-4 w-4" />
          Try again
        </Button>
      </div>
    </div>
  )
}
