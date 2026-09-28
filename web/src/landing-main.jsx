import { StrictMode } from 'react';
import '../style.css';
import { hydrateRoot } from 'react-dom/client';
import Landing from './Landing.jsx';

hydrateRoot(document.getElementById('root'),
  <StrictMode><Landing /></StrictMode>,
);
