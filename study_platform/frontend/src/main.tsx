import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Toaster } from 'sonner';
import { App } from './app';
import './styles.css';
const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 1500 } } });
ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode>
  <QueryClientProvider client={queryClient}>
    <BrowserRouter>
      <App />
      <Toaster richColors position="bottom-right" />
    </BrowserRouter>
  </QueryClientProvider>
</React.StrictMode>);
