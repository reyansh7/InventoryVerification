import { useState, useRef, useEffect } from 'react';
import { UploadCloud, Box, Layers, Loader2, ArrowRight, Database, AlertCircle, Check, X, FileSpreadsheet, Edit3, Trash2, BrainCircuit } from 'lucide-react';
import './index.css';

const API_URL = "http://localhost:8000";

interface MediaItem {
  id: string;
  file: File;
  previewUrl: string;
  isVideo: boolean;
  status: 'pending' | 'analyzing' | 'done' | 'error' | 'duplicate_pending' | 'quality_warning' | 'past_scan';
  box_count?: number;
  pallet_count?: number;
  annotated_url?: string;
  error?: string;
  duplicate_classes?: string[];
  quality_reason?: string;
  manual_box_count?: number;
  manual_pallet_count?: number;
  scan_id?: number;
  file_path?: string;
  object_code?: string;
}

interface InventoryRecord {
  object_code: string;
  total_boxes: number;
  total_pallets: number;
  scan_count: number;
  expected_qty?: number;
}

interface ERPFile {
  id: number;
  filename: string;
  uploaded_at: string;
  items: { object_code: string; expected_qty: number }[];
}

function App() {
  const [mediaItems, setMediaItems] = useState<MediaItem[]>([]);
  const [objectCode, setObjectCode] = useState('');
  const [loading, setLoading] = useState(false);
  const [globalError, setGlobalError] = useState<string | null>(null);
  const [inventory, setInventory] = useState<InventoryRecord[]>([]);
  const [erpFiles, setErpFiles] = useState<ERPFile[]>([]);

  const [trainingScanId, setTrainingScanId] = useState<number | null>(null);
  const [trainingStatus, setTrainingStatus] = useState<{
    running: boolean; phase: string; total: number; labeled: number; failed: number; message: string;
  } | null>(null);
  
  // Poll training status every 3s when a job is running
  useEffect(() => {
    let interval: ReturnType<typeof setInterval> | null = null;
    const poll = async () => {
      try {
        const res = await fetch(`${API_URL}/autotrain/status`);
        if (res.ok) {
          const data = await res.json();
          setTrainingStatus(data);
          if (!data.running && interval) {
            clearInterval(interval);
            interval = null;
            // Keep final status visible for 10s then clear
            setTimeout(() => setTrainingStatus(null), 10000);
          }
        }
      } catch { /* backend not ready yet */ }
    };
    if (trainingStatus?.running) {
      interval = setInterval(poll, 3000);
    }
    return () => { if (interval) clearInterval(interval); };
  }, [trainingStatus?.running]);
  


  const handleExportCsv = () => {
    if (inventory.length === 0) {
      alert("No inventory data to export.");
      return;
    }
    // Build CSV in the same format as the ERP CSV (SKU, expected_qty)
    // but with the model's actual detected counts
    const rows = [
      ['SKU', 'detected_boxes', 'detected_pallets', 'total_detected', 'expected_qty', 'difference']
    ];
    inventory.forEach(record => {
      const boxes = record.total_boxes || 0;
      const pallets = record.total_pallets || 0;
      const expected = record.expected_qty ?? '';
      const diff = expected !== '' ? boxes - (expected as number) : '';
      rows.push([
        record.object_code,
        String(boxes),
        String(pallets),
        String(boxes + pallets),
        String(expected),
        String(diff)
      ]);
    });
    const csvContent = rows.map(r => r.map(v => `"${v}"`).join(',')).join('\n');
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `inventory_scan_report_${new Date().toISOString().split('T')[0]}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleAutoTrain = async (item: MediaItem) => {

    if (!item.scan_id) {
      alert("This item hasn't been saved to the database yet.");
      return;
    }
    if (trainingStatus?.running) {
      alert("A training job is already running. Please wait for it to finish.");
      return;
    }
    
    setTrainingScanId(item.scan_id);
    setTrainingStatus({ running: true, phase: 'starting', total: 1, labeled: 0, failed: 0, message: 'Starting...' });
    
    try {
      const res = await fetch(`${API_URL}/autotrain`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scan_ids: [item.scan_id], api_keys: [] })
      });
      const data = await res.json();
      if (data.status === 'busy') {
        alert(data.message);
        setTrainingStatus(data.training_status);
      }
    } catch (e) {
      console.error(e);
      setTrainingStatus({ running: false, phase: 'error', total: 1, labeled: 0, failed: 0, message: 'Failed to contact backend.' });
    } finally {
      setTimeout(() => setTrainingScanId(null), 5000);
    }
  };
  
  const handleAutoTrainAll = async () => {
    const scansToTrain = doneItems.map(item => item.scan_id).filter(id => id !== undefined) as number[];
    if (scansToTrain.length === 0) {
      alert("No completed scans available for training.");
      return;
    }

    if (trainingStatus?.running) {
      alert("A training job is already running. Please wait for it to finish.");
      return;
    }

    setTrainingStatus({ running: true, phase: 'starting', total: scansToTrain.length, labeled: 0, failed: 0, message: `Starting autotrain for ${scansToTrain.length} scan(s)...` });
    
    try {
      const res = await fetch(`${API_URL}/autotrain`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scan_ids: scansToTrain, api_keys: [] })
      });
      const data = await res.json();
      if (data.status === 'busy') {
        alert(data.message);
        setTrainingStatus(data.training_status);
      }
    } catch (e) {
      console.error(e);
      alert("Failed to start auto-training.");
    }
  };
  
  const fileInputRef = useRef<HTMLInputElement>(null);
  const erpInputRef = useRef<HTMLInputElement>(null);

  const fetchErpFiles = async () => {
    try {
      const res = await fetch(`${API_URL}/erp/files`);
      if (res.ok) {
        setErpFiles(await res.json());
      }
    } catch (err) {
      console.error(err);
    }
  };

  const fetchInventory = async () => {
    try {
      fetchErpFiles();
      const res = await fetch(`${API_URL}/inventory`);
      if (res.ok) {
        const data = await res.json();
        setInventory(data);
      }
    } catch (err) {
      console.error(err);
      setGlobalError('Failed to fetch inventory. Backend might be down.');
    }
  };

  useEffect(() => {
    fetchInventory();
    const interval = setInterval(fetchInventory, 5000);
    return () => clearInterval(interval);
  }, []);

  const fetchObjectScans = async (code: string) => {
    try {
      setObjectCode(code);
      const res = await fetch(`${API_URL}/inventory/${encodeURIComponent(code)}/scans`);
      if (res.ok) {
        const data = await res.json();
        const pastItems = data.map((scan: any) => ({
          id: `scan-${scan.id}`,
          previewUrl: scan.file_path ? `${API_URL}/${scan.file_path}` : '',
          annotated_url: scan.file_path ? `${API_URL}/${scan.file_path}` : '',
          isVideo: scan.file_path ? /\.(mp4|webm|mov|avi)$/i.test(scan.file_path) : false,
          status: 'past_scan' as const,
          box_count: scan.box_count,
          pallet_count: scan.pallet_count,
          scan_id: scan.id,
          file_path: scan.file_path,
          object_code: scan.object_code
        }));
        setMediaItems(pastItems);
        setGlobalError(null);
      }
    } catch (e) {
      console.error(e);
      setGlobalError('Failed to fetch past scans.');
    }
  };

  const handleClearDatabase = async () => {
    if (!confirm('Are you sure you want to delete all inventory records? This cannot be undone.')) return;
    try {
      const res = await fetch(`${API_URL}/inventory/clear`, { method: 'DELETE' });
      fetchInventory();
    } catch (e) {
      console.error(e);
      setGlobalError('Failed to clear database.');
    }
  };

  const handleDeleteClass = async (e: React.MouseEvent, code: string) => {
    e.stopPropagation();
    if (!confirm(`Are you sure you want to permanently delete ALL scans and data for class '${code}'?`)) return;
    
    try {
      const res = await fetch(`${API_URL}/inventory/class/${encodeURIComponent(code)}`, { method: 'DELETE' });
      fetchInventory();
      if (objectCode === code) {
        setMediaItems([]);
        setObjectCode('');
      }
    } catch (e) {
      console.error(e);
      setGlobalError(`Failed to delete class '${code}'.`);
    }
  };

  const handleDeleteErpFile = async (id: number) => {
    if (!confirm("Are you sure you want to delete this CSV? This will remove all expected quantities associated with it.")) return;
    try {
      await fetch(`${API_URL}/erp/files/${id}`, { method: 'DELETE' });
      fetchInventory();
    } catch (e) {
      console.error(e);
      setGlobalError("Failed to delete CSV.");
    }
  };

  const handleDeleteErpItem = async (csvId: number, objectCode: string) => {
    if (!confirm(`Are you sure you want to remove '${objectCode}' from this CSV?`)) return;
    try {
      await fetch(`${API_URL}/erp/files/${csvId}/items/${objectCode}`, { method: 'DELETE' });
      fetchInventory();
    } catch (e) {
      console.error(e);
      setGlobalError("Failed to remove item from CSV.");
    }
  };

  const handleDragStartItem = (e: React.DragEvent, sourceCode: string) => {
    e.dataTransfer.setData('text/plain', sourceCode);
  };

  const handleDropOnSku = async (e: React.DragEvent, targetCode: string) => {
    e.preventDefault();
    const sourceCode = e.dataTransfer.getData('text/plain');
    if (sourceCode && sourceCode !== targetCode) {
      if (confirm(`Merge all scans from '${sourceCode}' into '${targetCode}'?`)) {
        try {
          await fetch(`${API_URL}/inventory/merge`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ source_object_code: sourceCode, target_object_code: targetCode })
          });
          fetchInventory();
        } catch(err) {
          console.error(err);
        }
      }
    }
  };

  const handleDragOverSku = (e: React.DragEvent) => {
    e.preventDefault();
  };

  const handleDropOnCsv = async (e: React.DragEvent, csvId: number, csvFilename: string) => {
    e.preventDefault();
    const sourceCode = e.dataTransfer.getData('text/plain');
    if (sourceCode) {
      if (confirm(`Link class '${sourceCode}' to the ERP file '${csvFilename}'?`)) {
        try {
          // Backend resolves qty from this ERP's uploaded catalog (0 if class not in that ERP)
          await fetch(`${API_URL}/erp/files/${csvId}/items`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ object_code: sourceCode, expected_qty: 0 })
          });
          fetchInventory();
        } catch(err) {
          console.error(err);
        }
      }
    }
  };

  const handleErpUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    
    try {
      setLoading(true);
      const formData = new FormData();
      formData.append('file', file);
      
      const res = await fetch(`${API_URL}/erp/upload`, {
        method: 'POST',
        body: formData
      });
      
      if (!res.ok) throw new Error("ERP upload failed");
      await fetchInventory();
    } catch(e) {
      console.error(e);
      setGlobalError("Failed to upload ERP data. Ensure it is a valid CSV.");
    } finally {
      setLoading(false);
      if (erpInputRef.current) erpInputRef.current.value = '';
    }
  };

  const processFiles = (files: File[]) => {
    const newItems = files.map(file => ({
      id: Math.random().toString(36).substring(7),
      file,
      previewUrl: URL.createObjectURL(file),
      isVideo: file.type.startsWith('video/'),
      status: 'pending' as const,
      manual_box_count: 0,
      manual_pallet_count: 0
    }));
    setMediaItems(prev => [...prev, ...newItems]);
    setGlobalError(null);
  };

  const handleFileSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || []);
    if (files.length > 0) processFiles(files);
  };

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => e.preventDefault();

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    const files = Array.from(e.dataTransfer.files || []);
    if (files.length > 0) processFiles(files);
  };

  const analyzeFiles = async () => {
    if (!objectCode.trim()) {
      setGlobalError("Please enter an Object Code / SKU before analyzing.");
      return;
    }

    const pendingItems = mediaItems.filter(item => item.status === 'pending' || item.status === 'error');
    if (pendingItems.length === 0) return;

    setLoading(true);
    setGlobalError(null);
    
    setMediaItems(prev => prev.map(item => 
      (item.status === 'pending' || item.status === 'error') ? { ...item, status: 'analyzing' } : item
    ));

    const images = pendingItems.filter(item => !item.isVideo);
    const videos = pendingItems.filter(item => item.isVideo);

    try {
      // 1. Process Images
      if (images.length > 0) {
        const formData = new FormData();
        images.forEach(img => formData.append('files', img.file));
        formData.append('object_code', objectCode);
        
        const response = await fetch(`${API_URL}/analyze_batch`, {
          method: 'POST',
          body: formData,
        });

        if (!response.ok) throw new Error('Failed to analyze images');
        const data = await response.json();
        if (data.error) throw new Error(data.error);

        setMediaItems(prev => {
          const currentIds = new Set(prev.map(i => i.id));
          
          // Cleanup any that were deleted during analysis
          data.forEach((imgData: any, i: number) => {
            const originalItem = images[i];
            if (!currentIds.has(originalItem.id) && imgData.scan_id) {
               fetch(`${API_URL}/inventory/scan/${imgData.scan_id}`, { method: 'DELETE' }).then(() => fetchInventory());
            }
          });

          return prev.map(item => {
            const imgIndex = images.findIndex(img => img.id === item.id);
            if (imgIndex !== -1) {
              const isLowQuality = data[imgIndex].is_low_quality;
              const isDup = data[imgIndex].is_duplicate;
              
              return {
                ...item,
                status: isLowQuality ? 'quality_warning' : (isDup ? 'duplicate_pending' : 'done'),
                box_count: data[imgIndex].box_count,
                pallet_count: data[imgIndex].pallet_count,
                annotated_url: data[imgIndex].annotated_image,
                file_path: data[imgIndex].file_path,
                scan_id: data[imgIndex].scan_id,
                duplicate_classes: data[imgIndex].duplicate_classes,
                quality_reason: data[imgIndex].quality_reason,
                object_code: objectCode,
              };
            }
            return item;
          });
        });
      }

      // 2. Process Videos
      for (const video of videos) {
        try {
          const formData = new FormData();
          formData.append('file', video.file);
          formData.append('object_code', objectCode);

          const response = await fetch(`${API_URL}/analyze_video`, {
            method: 'POST',
            body: formData,
          });

          const data = await response.json();
          if (!response.ok) {
            throw new Error(data.error || `Failed to analyze video: ${video.file.name}`);
          }
          if (data.error) {
            throw new Error(data.error);
          }
          
          const isLowQuality = data.is_low_quality;
          const isDuplicate = data.is_duplicate;

          setMediaItems(prev => {
            const stillExists = prev.some(i => i.id === video.id);
            if (!stillExists) {
               if (data.scan_id) {
                 fetch(`${API_URL}/inventory/scan/${data.scan_id}`, { method: 'DELETE' }).then(() => fetchInventory());
               }
               return prev;
            }

            return prev.map(item => {
              if (item.id === video.id) {
                return {
                  ...item,
                  status: isLowQuality ? 'quality_warning' : (isDuplicate ? 'duplicate_pending' : 'done'),
                  box_count: data.box_count,
                  pallet_count: data.pallet_count,
                  annotated_url: data.annotated_image,
                  file_path: data.file_path,
                  scan_id: data.scan_id,
                  duplicate_classes: data.duplicate_classes || [],
                  quality_reason: data.quality_reason,
                  object_code: objectCode,
                };
              }
              return item;
            });
          });
        } catch (vidErr) {
          console.error(vidErr);
          const message = vidErr instanceof Error ? vidErr.message : 'Failed';
          setMediaItems(prev => prev.map(item => item.id === video.id ? { ...item, status: 'error', error: message } : item));
        }
      }
    } catch (err) {
      setGlobalError(err instanceof Error ? err.message : 'An error occurred during analysis');
      setMediaItems(prev => prev.map(item => item.status === 'analyzing' ? { ...item, status: 'error' } : item));
    } finally {
      setLoading(false);
      fetchInventory();
    }
  };

  const handleForceAdd = async (item: MediaItem) => {
    try {
      const res = await fetch(`${API_URL}/inventory/add`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          object_code: objectCode,
          filename: item.file?.name || "duplicate",
          file_size: item.file?.size || 0,
          box_count: item.box_count || 0,
          pallet_count: item.pallet_count || 0,
          file_path: item.file_path
        })
      });
      if (!res.ok) throw new Error("Failed to add");
      const data = await res.json();
      setMediaItems(prev => prev.map(i => i.id === item.id ? { ...i, status: 'done', scan_id: data.scan_id, object_code: objectCode } : i));
      fetchInventory();
    } catch (e) {
      console.error(e);
      setGlobalError('Failed to add duplicate to inventory.');
    }
  };

  const handleUpdateManualCount = (id: string, field: 'box' | 'pallet', value: string) => {
    const num = parseInt(value) || 0;
    setMediaItems(prev => prev.map(item => item.id === id ? { ...item, [field === 'box' ? 'manual_box_count' : 'manual_pallet_count']: num } : item));
  };
  
  const handleSaveManualCount = async (item: MediaItem) => {
    try {
      const res = await fetch(`${API_URL}/inventory/add`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          object_code: objectCode,
          filename: item.file?.name || "manual",
          file_size: item.file?.size || 0,
          box_count: item.manual_box_count || 0,
          pallet_count: item.manual_pallet_count || 0,
          file_path: item.file_path
        })
      });
      if (!res.ok) throw new Error("Failed to save");
      
      const data = await res.json();
      
      setMediaItems(prev => prev.map(i => i.id === item.id ? { 
        ...i, 
        status: 'done', 
        scan_id: data.scan_id,
        box_count: item.manual_box_count || 0, 
        pallet_count: item.manual_pallet_count || 0,
        quality_reason: undefined,
        object_code: objectCode
      } : i));
      fetchInventory();
    } catch (e) {
      console.error(e);
      setGlobalError('Failed to save manual count.');
    }
  };

  const handleRemove = async (item: MediaItem) => {
    if (item.scan_id) {
      if (item.object_code && item.object_code !== objectCode) {
        // Automatically hide from screen without deleting from DB
        setMediaItems(prev => prev.filter(i => i.id !== item.id));
        return;
      } else {
        if (!confirm(`Are you sure you want to permanently delete this scan for '${item.object_code || objectCode}' from the database?`)) return;
      }

      try {
        await fetch(`${API_URL}/inventory/scan/${item.scan_id}`, { method: 'DELETE' });
        fetchInventory();
      } catch (e) {
        console.error(e);
        setGlobalError("Failed to delete scan.");
        return;
      }
    }
    setMediaItems(prev => prev.filter(i => i.id !== item.id));
  };

  const reset = () => {
    setMediaItems([]);
    setObjectCode('');
    setGlobalError(null);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const doneItems = mediaItems.filter(item => item.status === 'done' || item.status === 'past_scan');
  const duplicateItems = mediaItems.filter(item => item.status === 'duplicate_pending');
  const qualityItems = mediaItems.filter(item => item.status === 'quality_warning');
  const otherItems = mediaItems.filter(item => !['done', 'duplicate_pending', 'quality_warning', 'past_scan'].includes(item.status));

  const renderMediaCard = (item: MediaItem) => {
    const isDup = item.status === 'duplicate_pending';
    const isQuality = item.status === 'quality_warning';
    
    let bgColor = 'rgba(255,255,255,0.03)';
    let borderColor = 'rgba(255,255,255,0.08)';
    let labelBg = 'rgba(0,0,0,0.6)';
    
    if (isDup) {
      bgColor = 'rgba(245, 158, 11, 0.1)';
      borderColor = 'rgba(245, 158, 11, 0.4)';
      labelBg = '#f59e0b';
    } else if (isQuality) {
      bgColor = 'rgba(239, 68, 68, 0.1)';
      borderColor = 'rgba(239, 68, 68, 0.4)';
      labelBg = '#ef4444';
    }

    return (
      <div key={item.id} style={{ background: bgColor, borderRadius: '12px', padding: '16px', border: `1px solid ${borderColor}`, position: 'relative' }}>
        <button 
          onClick={() => handleRemove(item)}
          style={{ position: 'absolute', top: '-8px', right: '-8px', background: '#ef4444', color: 'white', border: 'none', borderRadius: '50%', width: '24px', height: '24px', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', zIndex: 10 }}
        >
          <X size={14} />
        </button>
        <div style={{ marginBottom: '12px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span className="image-label" style={{ background: labelBg, padding: '4px 8px', borderRadius: '4px', color: 'white', fontSize: '12px', fontWeight: 'bold' }}>
            {item.isVideo ? 'Video' : 'Photo'} 
            {item.status === 'done' && ` (Added to ${item.object_code || 'DB'})`}
            {item.status === 'past_scan' && ` (History: ${item.object_code})`}
            {isDup && ' (Duplicate)'}
            {isQuality && ' (Low Quality)'}
          </span>
          
          {item.status === 'analyzing' && <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#9ca3af', fontSize: '12px' }}><Loader2 className="spinner" size={14} /> Analyzing</div>}
          {item.status === 'error' && <span style={{ color: '#f87171', fontSize: '12px', fontWeight: 'bold' }}>{item.error || 'Error'}</span>}
        </div>

        <div style={{ borderRadius: '8px', overflow: 'hidden', background: '#000', display: 'flex', justifyContent: 'center', alignItems: 'center', aspectRatio: '16/9' }}>
          {item.isVideo ? (
            <video
              key={item.annotated_url || item.previewUrl}
              src={item.annotated_url || item.previewUrl}
              controls
              playsInline
              preload="metadata"
              className="preview-image"
              style={{ width: '100%', height: '100%', objectFit: 'contain', background: '#000' }}
            />
          ) : (
            <img src={item.annotated_url || item.previewUrl} className="preview-image" style={{ width: '100%', height: '100%', objectFit: 'contain' }} />
          )}
        </div>

        {(item.status === 'done' || item.status === 'past_scan' || isDup) && (
          <div style={{ display: 'flex', gap: '16px', marginTop: '16px', padding: '12px', background: 'rgba(0,0,0,0.3)', borderRadius: '8px', alignItems: 'center', justifyContent: 'space-between' }}>
            <div style={{ display: 'flex', gap: '16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Box size={18} className="box-icon" /> <span style={{ fontSize: '15px', fontWeight: 'bold', color: 'white' }}>{item.box_count} Boxes</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Layers size={18} className="pallet-icon" /> <span style={{ fontSize: '15px', fontWeight: 'bold', color: 'white' }}>{item.pallet_count} Pallets</span>
              </div>
            </div>
            
            <button 
              className="btn btn-primary" 
              onClick={() => handleAutoTrain(item)} 
              disabled={trainingScanId === item.scan_id}
              style={{ padding: '6px 12px', fontSize: '12px', background: '#3b82f6', display: 'flex', alignItems: 'center', gap: '6px' }}
            >
              {trainingScanId === item.scan_id ? <Loader2 size={14} className="spinner" /> : <BrainCircuit size={14}/>}
              {trainingScanId === item.scan_id ? 'Training...' : 'Auto Train AI'}
            </button>
          </div>
        )}

        {isDup && (
          <div style={{ marginTop: '16px' }}>
            <p style={{ fontSize: '13px', color: '#fcd34d', marginBottom: '8px' }}>This exact file was already scanned for: <strong>{item.duplicate_classes?.join(', ')}</strong>. Count it again for <strong>{objectCode}</strong>?</p>
            <div style={{ display: 'flex', gap: '8px' }}>
              <button className="btn btn-primary" onClick={() => handleForceAdd(item)} style={{ flex: 1, padding: '8px', fontSize: '13px', background: '#f59e0b', color: '#000' }}><Check size={16}/> Yes, Add</button>
              <button className="btn btn-secondary" onClick={() => handleRemove(item)} style={{ flex: 1, padding: '8px', fontSize: '13px' }}><X size={16}/> No, Remove</button>
            </div>
          </div>
        )}

        {isQuality && (
          <div style={{ marginTop: '16px' }}>
            <p style={{ fontSize: '13px', color: '#fca5a5', marginBottom: '12px' }}>
              <AlertCircle size={14} style={{ display: 'inline', marginRight: '4px', verticalAlign: 'text-bottom' }} />
              <strong>AI Check Failed:</strong> {item.quality_reason} Please enter count manually or discard.
            </p>
            
            <div style={{ display: 'flex', gap: '12px', marginBottom: '12px' }}>
              <div style={{ flex: 1 }}>
                <label style={{ display: 'block', fontSize: '12px', color: '#9ca3af', marginBottom: '4px' }}>Boxes</label>
                <input type="number" min="0" value={item.manual_box_count} onChange={(e) => handleUpdateManualCount(item.id, 'box', e.target.value)} style={{ width: '100%', padding: '8px', borderRadius: '4px', background: 'rgba(0,0,0,0.5)', border: '1px solid rgba(255,255,255,0.2)', color: 'white' }} />
              </div>
              <div style={{ flex: 1 }}>
                <label style={{ display: 'block', fontSize: '12px', color: '#9ca3af', marginBottom: '4px' }}>Pallets</label>
                <input type="number" min="0" value={item.manual_pallet_count} onChange={(e) => handleUpdateManualCount(item.id, 'pallet', e.target.value)} style={{ width: '100%', padding: '8px', borderRadius: '4px', background: 'rgba(0,0,0,0.5)', border: '1px solid rgba(255,255,255,0.2)', color: 'white' }} />
              </div>
            </div>

            <div style={{ display: 'flex', gap: '8px' }}>
              <button className="btn btn-primary" onClick={() => handleSaveManualCount(item)} style={{ flex: 1, padding: '8px', fontSize: '13px', background: '#ef4444' }}><Edit3 size={16}/> Save Manual</button>
              <button className="btn btn-secondary" onClick={() => handleRemove(item)} style={{ flex: 1, padding: '8px', fontSize: '13px' }}><X size={16}/> Discard</button>
            </div>
          </div>
        )}
      </div>
    );
  };

  const renderInventoryRecord = (record: InventoryRecord, fromCsvId?: number) => {
    const isVerified = record.expected_qty !== undefined && record.expected_qty !== null;
    const actualQty = record.total_boxes || 0;
    const expectedQty = record.expected_qty || 0;
    const diff = actualQty - expectedQty;
    
    let statusColor = '#9ca3af';
    let statusText = '';
    
    if (isVerified) {
      if (diff === 0) {
        statusColor = '#4ade80';
        statusText = 'OK';
      } else if (diff < 0) {
        statusColor = '#f87171';
        statusText = `Missing ${Math.abs(diff)}`;
      } else {
        statusColor = '#facc15';
        statusText = `Surplus ${diff}`;
      }
    }

    return (
      <div 
        key={record.object_code} 
        draggable={true}
        onDragStart={(e) => handleDragStartItem(e, record.object_code)}
        onClick={() => fetchObjectScans(record.object_code)}
        style={{ background: 'rgba(0,0,0,0.3)', borderRadius: '8px', padding: '16px', borderLeft: `4px solid ${isVerified ? statusColor : '#60a5fa'}`, cursor: 'grab', transition: 'background 0.2s', marginBottom: '12px' }}
        onMouseOver={(e) => e.currentTarget.style.background = 'rgba(255,255,255,0.05)'}
        onMouseOut={(e) => e.currentTarget.style.background = 'rgba(0,0,0,0.3)'}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
          <h3 style={{ margin: 0, color: 'white', fontSize: '18px' }}>{record.object_code}</h3>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            {isVerified ? (
              <span style={{ fontSize: '12px', fontWeight: 'bold', color: statusColor, background: 'rgba(255,255,255,0.05)', padding: '4px 8px', borderRadius: '4px' }}>
                {statusText}
              </span>
            ) : (
              <span style={{ fontSize: '12px', color: '#9ca3af' }}>{record.scan_count} scan(s)</span>
            )}
            
            {fromCsvId ? (
              <button 
                onClick={(e) => { e.stopPropagation(); handleDeleteErpItem(fromCsvId, record.object_code); }}
                style={{ background: 'transparent', border: 'none', color: '#ef4444', cursor: 'pointer', padding: '4px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
                title={`Remove ${record.object_code} from CSV`}
              >
                <Trash2 size={16} />
              </button>
            ) : (
              <button 
                onClick={(e) => { e.stopPropagation(); handleDeleteClass(e, record.object_code); }}
                style={{ background: 'transparent', border: 'none', color: '#ef4444', cursor: 'pointer', padding: '4px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
                title={`Delete ${record.object_code}`}
              >
                <Trash2 size={16} />
              </button>
            )}
          </div>
        </div>
        
        <div style={{ display: 'flex', gap: '16px', marginBottom: isVerified ? '12px' : '0' }}>
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Box size={16} className="box-icon" /> 
            <span style={{ color: 'white', fontWeight: 'bold' }}>{actualQty}</span>
          </div>
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Layers size={16} className="pallet-icon" /> 
            <span style={{ color: 'white', fontWeight: 'bold' }}>{record.total_pallets || 0}</span>
          </div>
        </div>
        
        {isVerified && (
          <div style={{ fontSize: '13px', color: '#9ca3af', borderTop: '1px solid rgba(255,255,255,0.1)', paddingTop: '8px', display: 'flex', justifyContent: 'space-between' }}>
            <span>ERP Expected Qty: <strong style={{ color: 'white' }}>{expectedQty}</strong></span>
            {record.scan_count > 0 && <span>({record.scan_count} Scans)</span>}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="app-container">
      <div className="background-glow glow-1"></div>
      <div className="background-glow glow-2"></div>
      
      <main className="main-content" style={{ maxWidth: '1400px', margin: '0 auto', padding: '40px 20px' }}>
        <header className="header" style={{ marginBottom: '40px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <div className="logo-container">
              <Layers className="logo-icon" size={32} />
              <h1>Inventory AI</h1>
            </div>
            <p className="subtitle">Warehouse Scanning System</p>
          </div>

        </header>

        {globalError && (
          <div className="error-message" style={{ marginBottom: '20px' }}>
            <AlertCircle size={20} />
            <p style={{ margin: 0 }}>{globalError}</p>
            <button className="btn btn-secondary" onClick={() => setGlobalError(null)}>Dismiss</button>
          </div>
        )}

        {trainingStatus && (
          <div style={{
            marginBottom: '20px', padding: '16px 20px', borderRadius: '12px',
            background: trainingStatus.phase === 'done' ? 'rgba(74,222,128,0.1)' :
                        trainingStatus.phase === 'error' ? 'rgba(239,68,68,0.1)' :
                        'rgba(59,130,246,0.1)',
            border: `1px solid ${trainingStatus.phase === 'done' ? 'rgba(74,222,128,0.4)' :
                                  trainingStatus.phase === 'error' ? 'rgba(239,68,68,0.4)' :
                                  'rgba(59,130,246,0.4)'}`,
            display: 'flex', flexDirection: 'column', gap: '8px'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                {trainingStatus.running && <Loader2 size={16} className="spinner" style={{ color: '#60a5fa' }} />}
                {trainingStatus.phase === 'done' && <span style={{ fontSize: '16px' }}>✅</span>}
                {trainingStatus.phase === 'error' && <AlertCircle size={16} style={{ color: '#f87171' }} />}
                <span style={{ fontWeight: 'bold', color: 'white', fontSize: '14px' }}>
                  {trainingStatus.running ? `AI Training: ${trainingStatus.phase.charAt(0).toUpperCase() + trainingStatus.phase.slice(1)}` :
                   trainingStatus.phase === 'done' ? 'Training Complete' : 'Training Failed'}
                </span>
              </div>
              {trainingStatus.phase === 'labeling' && (
                <span style={{ fontSize: '12px', color: '#9ca3af' }}>
                  {trainingStatus.labeled}/{trainingStatus.total} labeled · {trainingStatus.failed} skipped
                </span>
              )}
              {!trainingStatus.running && (
                <button onClick={() => setTrainingStatus(null)} style={{ background: 'transparent', border: 'none', color: '#9ca3af', cursor: 'pointer', fontSize: '16px', padding: '2px 6px' }}>✕</button>
              )}
            </div>
            {trainingStatus.phase === 'labeling' && trainingStatus.total > 0 && (
              <div style={{ background: 'rgba(0,0,0,0.4)', borderRadius: '4px', height: '6px', overflow: 'hidden' }}>
                <div style={{
                  height: '100%', borderRadius: '4px', background: 'linear-gradient(90deg, #3b82f6, #60a5fa)',
                  width: `${Math.round((trainingStatus.labeled / trainingStatus.total) * 100)}%`,
                  transition: 'width 0.5s ease'
                }} />
              </div>
            )}
            <p style={{ margin: 0, fontSize: '13px', color: '#9ca3af' }}>{trainingStatus.message}</p>
          </div>
        )}

        <div style={{ display: 'flex', gap: '40px', flexWrap: 'wrap' }}>
          <div style={{ flex: '1 1 600px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
            <div className="glass-card" style={{ padding: '24px' }}>
              <div style={{ marginBottom: '20px' }}>
                <label style={{ display: 'block', color: 'white', fontWeight: 'bold', marginBottom: '8px' }}>Object Code / SKU</label>
                <input 
                  type="text" 
                  value={objectCode}
                  onChange={(e) => setObjectCode(e.target.value)}
                  placeholder="e.g. ITEM-001"
                  style={{ width: '100%', padding: '12px 16px', borderRadius: '8px', background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(255,255,255,0.2)', color: 'white', fontSize: '16px' }}
                />
              </div>

              {mediaItems.length === 0 ? (
                <div className="dropzone" onDragOver={handleDragOver} onDrop={handleDrop} onClick={() => fileInputRef.current?.click()}>
                  <div className="dropzone-content">
                    <div className="icon-wrapper"><UploadCloud size={48} className="upload-icon" /></div>
                    <h3>Drop images & videos here</h3>
                    <p>or click to browse from your computer</p>
                    <input type="file" multiple accept="image/*,video/mp4,video/webm,video/quicktime" ref={fileInputRef} onChange={handleFileSelect} className="hidden-input" />
                  </div>
                </div>
              ) : (
                <>
                  {qualityItems.length > 0 && (
                    <div style={{ marginBottom: '32px', background: 'rgba(239, 68, 68, 0.05)', borderRadius: '12px', padding: '20px', border: '1px solid rgba(239, 68, 68, 0.2)' }}>
                      <h3 style={{ color: '#ef4444', marginTop: 0, display: 'flex', alignItems: 'center', gap: '8px' }}><AlertCircle size={20} /> Quality Assessment Failed</h3>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '20px' }}>
                        {qualityItems.map(item => renderMediaCard(item))}
                      </div>
                    </div>
                  )}

                  {duplicateItems.length > 0 && (
                    <div style={{ marginBottom: '32px', background: 'rgba(245, 158, 11, 0.05)', borderRadius: '12px', padding: '20px', border: '1px solid rgba(245, 158, 11, 0.2)' }}>
                      <h3 style={{ color: '#fbbf24', marginTop: 0, display: 'flex', alignItems: 'center', gap: '8px' }}><AlertCircle size={20} /> Duplicate Scans Detected</h3>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '20px' }}>
                        {duplicateItems.map(item => renderMediaCard(item))}
                      </div>
                    </div>
                  )}

                  {(doneItems.length > 0 || otherItems.length > 0) && (
                    <div style={{ marginBottom: '20px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                         <h3 style={{ color: 'white', margin: 0 }}>Active Scans</h3>
                         {doneItems.length > 0 && (
                            <button className="btn btn-primary" onClick={handleAutoTrainAll} style={{ padding: '6px 12px', fontSize: '13px', background: '#3b82f6', display: 'flex', alignItems: 'center', gap: '6px' }}>
                              <BrainCircuit size={16} /> Train All {doneItems.length} Scans
                            </button>
                         )}
                      </div>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '20px' }}>
                        {doneItems.map(item => renderMediaCard(item))}
                        {otherItems.map(item => renderMediaCard(item))}
                      </div>
                    </div>
                  )}

                  {!loading && (
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '20px', padding: '20px', background: 'rgba(255,255,255,0.05)', borderRadius: '12px' }}>
                      <div style={{ display: 'flex', gap: '12px' }}>
                        <button className="btn btn-secondary" onClick={() => fileInputRef.current?.click()}>+ Add Files</button>
                        <input type="file" multiple accept="image/*,video/mp4,video/webm,video/quicktime" ref={fileInputRef} onChange={handleFileSelect} className="hidden-input" />
                        <button className="btn btn-secondary" onClick={reset}>Clear Session</button>
                      </div>
                      
                      {otherItems.some(i => i.status === 'pending' || i.status === 'error') && (
                        <button className="btn btn-primary" onClick={analyzeFiles}>
                          Analyze Pending <ArrowRight size={18} />
                        </button>
                      )}
                    </div>
                  )}

                  {loading && (
                    <div className="loading-state" style={{ padding: '40px 0' }}>
                      <Loader2 className="spinner" size={32} />
                      <p>Running YOLO inference...</p>
                    </div>
                  )}
                </>
              )}
            </div>
          </div>

          <div style={{ flex: '1 1 450px', maxWidth: '500px' }}>
            <div className="glass-card" style={{ padding: '24px', position: 'sticky', top: '40px' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '24px', paddingBottom: '16px', borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                  <Database size={24} style={{ color: '#60a5fa' }} />
                  <h2 style={{ margin: 0, color: 'white', fontSize: '20px' }}>Warehouse Inventory</h2>
                </div>
                
                <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                  <button className="btn btn-outline" onClick={() => erpInputRef.current?.click()} style={{ fontSize: '12px', padding: '6px 10px', color: 'white', borderColor: 'rgba(255,255,255,0.3)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <FileSpreadsheet size={14} /> Upload ERP
                  </button>
                  <input type="file" accept=".csv" ref={erpInputRef} onChange={handleErpUpload} className="hidden-input" />

                  {inventory.length > 0 && (
                    <button className="btn btn-outline" onClick={handleExportCsv} style={{ fontSize: '12px', padding: '6px 10px', color: '#4ade80', borderColor: 'rgba(74,222,128,0.5)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <FileSpreadsheet size={14} /> Export CSV
                    </button>
                  )}

                  {inventory.length > 0 && (
                    <button className="btn btn-outline" onClick={handleClearDatabase} style={{ fontSize: '12px', padding: '6px 10px', borderColor: '#f87171', color: '#f87171' }}>
                      Clear DB
                    </button>
                  )}
                </div>
              </div>

              {/* Uploaded ERP Files Section */}
              {erpFiles.length > 0 && (
                <div style={{ marginBottom: '32px' }}>
                  <h3 style={{ color: 'white', marginBottom: '16px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <FileSpreadsheet size={20} /> Uploaded ERP Files
                  </h3>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                    {erpFiles.map(file => (
                      <div 
                        key={file.id} 
                        className="glass-card" 
                        onDrop={(e) => handleDropOnCsv(e, file.id, file.filename)}
                        onDragOver={handleDragOverSku}
                        style={{ padding: '16px', background: 'rgba(59,130,246,0.05)', border: '1px solid rgba(59,130,246,0.2)' }}
                      >
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: file.items.length > 0 ? '12px' : '0', borderBottom: file.items.length > 0 ? '1px solid rgba(255,255,255,0.1)' : 'none', paddingBottom: file.items.length > 0 ? '12px' : '0' }}>
                          <span style={{ color: 'white', fontWeight: 'bold' }}>{file.filename}</span>
                          <button onClick={() => handleDeleteErpFile(file.id)} style={{ padding: '4px', background: 'transparent', border: 'none', color: '#ef4444', cursor: 'pointer' }}>
                            <Trash2 size={16} />
                          </button>
                        </div>
                        <div style={{ display: 'flex', flexDirection: 'column', maxHeight: '400px', overflowY: 'auto', paddingRight: '4px' }}>
                          {file.items.map(item => {
                            const invRec = inventory.find(i => i.object_code === item.object_code);
                            return renderInventoryRecord({
                              object_code: item.object_code,
                              total_boxes: invRec?.total_boxes ?? 0,
                              total_pallets: invRec?.total_pallets ?? 0,
                              scan_count: invRec?.scan_count ?? 0,
                              // Always show THIS ERP file's expected qty
                              expected_qty: item.expected_qty,
                            }, file.id);
                          })}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {inventory.length === 0 ? (
                <div style={{ textAlign: 'center', padding: '40px 0', color: '#9ca3af' }}>
                  <p>No inventory records found.</p>
                  <p style={{ fontSize: '13px' }}>Upload an ERP CSV or scan objects to build your database.</p>
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column' }}>
                  {inventory
                    .filter(record => !erpFiles.some(f => f.items.some(i => i.object_code === record.object_code)))
                    .map(record => renderInventoryRecord(record))
                  }
                </div>
              )}
            </div>
          </div>
        </div>

      </main>
    </div>
  );
}

export default App;
