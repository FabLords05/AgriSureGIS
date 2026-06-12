import { useState } from 'react';
import { TextField, Button, Card, CardContent, Select, MenuItem, FormControl, InputLabel, type SelectChangeEvent } from '@mui/material';
import { Lock, User } from 'lucide-react';

interface LoginProps {
  onLogin: (username: string, role: string) => void;
}

export function Login({ onLogin }: LoginProps) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState('gis-specialist');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (username && password) {
      onLogin(username, role);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-[var(--green-500)] via-[var(--blue-500)] to-[var(--gold-500)]">
      <Card className="w-full max-w-md shadow-2xl">
        <CardContent className="p-8">
          <div className="text-center mb-8">
            <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-[var(--primary)] mb-4">
              <Lock className="w-8 h-8 text-white" />
            </div>
            <h1 className="text-3xl mb-2" style={{ color: 'var(--primary)' }}>AgrisureGIS</h1>
            <p className="text-muted-foreground">Disaster Risk Assessment System</p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <TextField
              fullWidth
              label="Username"
              variant="outlined"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              slotProps={{
                input: { startAdornment: <User className="w-5 h-5 mr-2" style={{ color: 'var(--muted-foreground)' }} /> }
              }}
              required
            />

            <TextField
              fullWidth
              label="Password"
              type="password"
              variant="outlined"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              slotProps={{
                input: { startAdornment: <Lock className="w-5 h-5 mr-2" style={{ color: 'var(--muted-foreground)' }} /> }
              }}
              required
            />

            <FormControl fullWidth>
              <InputLabel>Role</InputLabel>
              <Select
                value={role}
                label="Role"
                onChange={(e: SelectChangeEvent) => setRole(e.target.value)}
              >
                <MenuItem value="gis-specialist">GIS Specialist</MenuItem>
                <MenuItem value="admin">System Administrator</MenuItem>
              </Select>
            </FormControl>

            <Button
              type="submit"
              variant="contained"
              fullWidth
              size="large"
              sx={{
                bgcolor: 'var(--primary)',
                '&:hover': { bgcolor: 'var(--green-600)' },
                textTransform: 'none',
                py: 1.5
              }}
            >
              Sign In
            </Button>
          </form>

          <div className="mt-6 text-center text-sm text-muted-foreground">
            <p>Philippine Crop Insurance Corporation</p>
            <p className="mt-1">PCIC Automated Disaster Assessment</p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
