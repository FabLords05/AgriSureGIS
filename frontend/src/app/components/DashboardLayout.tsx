import { ReactNode, useState } from 'react';
import {
  Drawer,
  List,
  ListItem,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  AppBar,
  Toolbar,
  IconButton,
  Switch,
  Box
} from '@mui/material';
import {
  Home,
  Map,
  FileText,
  Settings,
  Moon,
  Sun,
  LogOut,
  Menu,
  X
} from 'lucide-react';

interface DashboardLayoutProps {
  children: ReactNode;
  currentModule: string;
  onModuleChange: (module: string) => void;
  onLogout: () => void;
  isDark: boolean;
  onThemeToggle: () => void;
  username: string;
  role: string;
}

const modules = [
  { id: 'home', label: 'Monitoring & Extraction', icon: Home },
  { id: 'spatial', label: 'Spatial Analysis & Import', icon: Map },
  { id: 'assessment', label: 'Assessment & Reporting', icon: FileText },
  { id: 'settings', label: 'Calibration & Settings', icon: Settings }
];

export function DashboardLayout({
  children,
  currentModule,
  onModuleChange,
  onLogout,
  isDark,
  onThemeToggle,
  username,
  role
}: DashboardLayoutProps) {
  const [sidebarOpen, setSidebarOpen] = useState(true);

  const drawerWidth = 280;

  return (
    <div className="flex h-screen overflow-hidden">
      <AppBar
        position="fixed"
        sx={{
          bgcolor: 'var(--primary)',
          zIndex: 1300,
          boxShadow: '0 2px 8px rgba(0,0,0,0.1)'
        }}
      >
        <Toolbar>
          <IconButton
            edge="start"
            color="inherit"
            onClick={() => setSidebarOpen(!sidebarOpen)}
            sx={{ mr: 2 }}
          >
            {sidebarOpen ? <X /> : <Menu />}
          </IconButton>

          <div className="flex-1">
            <h1 className="text-xl text-white font-medium">AgrisureGIS System</h1>
            <p className="text-xs text-white/80">Philippine Crop Insurance Corporation</p>
          </div>

          <div className="flex items-center gap-4">
            <div className="text-right mr-4">
              <p className="text-sm text-white">{username}</p>
              <p className="text-xs text-white/70">{role === 'admin' ? 'System Administrator' : 'GIS Specialist'}</p>
            </div>

            <div className="flex items-center gap-2">
              <Sun className="w-4 h-4 text-white" />
              <Switch
                checked={isDark}
                onChange={onThemeToggle}
                sx={{
                  '& .MuiSwitch-thumb': { bgcolor: 'white' },
                  '& .MuiSwitch-track': { bgcolor: 'rgba(255,255,255,0.3)' }
                }}
              />
              <Moon className="w-4 h-4 text-white" />
            </div>

            <IconButton color="inherit" onClick={onLogout}>
              <LogOut className="w-5 h-5" />
            </IconButton>
          </div>
        </Toolbar>
      </AppBar>

      <Drawer
        variant="persistent"
        open={sidebarOpen}
        sx={{
          width: drawerWidth,
          flexShrink: 0,
          '& .MuiDrawer-paper': {
            width: drawerWidth,
            boxSizing: 'border-box',
            bgcolor: 'var(--sidebar)',
            borderRight: '1px solid var(--sidebar-border)',
            top: '64px',
            height: 'calc(100vh - 64px)'
          }
        }}
      >
        <Box sx={{ overflow: 'auto', mt: 2 }}>
          <List>
            {modules.map((module) => {
              const Icon = module.icon;
              const isActive = currentModule === module.id;

              return (
                <ListItem key={module.id} disablePadding sx={{ mb: 1, px: 2 }}>
                  <ListItemButton
                    selected={isActive}
                    onClick={() => onModuleChange(module.id)}
                    sx={{
                      borderRadius: '8px',
                      bgcolor: isActive ? 'var(--sidebar-primary)' : 'transparent',
                      color: isActive ? 'var(--sidebar-primary-foreground)' : 'var(--sidebar-foreground)',
                      '&:hover': {
                        bgcolor: isActive ? 'var(--green-600)' : 'var(--sidebar-accent)'
                      },
                      '&.Mui-selected': {
                        bgcolor: 'var(--sidebar-primary)',
                        '&:hover': { bgcolor: 'var(--green-600)' }
                      }
                    }}
                  >
                    <ListItemIcon sx={{ color: 'inherit', minWidth: 40 }}>
                      <Icon className="w-5 h-5" />
                    </ListItemIcon>
                    <ListItemText
                      primary={module.label}
                      primaryTypographyProps={{
                        fontSize: '0.9rem',
                        fontWeight: isActive ? 500 : 400
                      }}
                    />
                  </ListItemButton>
                </ListItem>
              );
            })}
          </List>
        </Box>
      </Drawer>

      <main
        style={{
          flexGrow: 1,
          marginLeft: sidebarOpen ? `${drawerWidth}px` : 0,
          marginTop: '64px',
          transition: 'margin-left 0.2s',
          height: 'calc(100vh - 64px)',
          overflow: 'auto',
          backgroundColor: 'var(--background)'
        }}
      >
        {children}
      </main>
    </div>
  );
}
