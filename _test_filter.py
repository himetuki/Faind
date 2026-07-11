import config
cfg = config.load_config()
sf = cfg.get('search_filters', {})
default_sf = config.DEFAULT_CONFIG.get('search_filters', {})
if not sf.get('exclude_folders'):
    sf['exclude_folders'] = default_sf.get('exclude_folders', [])
print('exclude_folders:', sf['exclude_folders'])
print('enabled:', sf.get('enabled'))
print('folder_sort_order:', sf.get('folder_sort_order'))