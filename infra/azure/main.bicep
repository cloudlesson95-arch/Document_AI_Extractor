// Azure resources for Document AI Extractor, deployed into the app's own resource group by setup.ps1. The deploy
// workflow (.github/workflows/deploy-azure.yml) creates the Container App itself, from the first image it pushes, so a
// rerun of this template never resets the running image or its settings.

@description('Prefix of every resource name: 2-9 lowercase letters or digits')
@minLength(2)
@maxLength(9)
param appName string

param location string = resourceGroup().location

@description('Object ID of the service principal the GitHub deploy workflow signs in as')
param deployPrincipalId string

@description('Object ID of the user running setup.ps1, who stores the Gemini key in Key Vault')
param operatorPrincipalId string

// Storage account, registry and vault names are global: a suffix unique to this resource group keeps them free
var suffix = uniqueString(resourceGroup().id)

// Built-in role IDs
var roles = {
  acrPull: '7f951dda-4ed3-4680-a7ca-43fe172d538d'
  acrPush: '8311e382-0749-4cb8-b61a-304f252e45ec'
  blobDataContributor: 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
  tableDataContributor: '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3'
  keyVaultSecretsOfficer: 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'
  containerAppsContributor: '358470bc-b998-42bd-ab17-a7e34c199c0f'
  managedIdentityOperator: 'f1a07417-d97a-45cb-824c-7a7467783830'
  reader: 'acdd72a7-3385-48ef-bd42-f606fba81ae7'
}

// The app's identity: it pulls the image and reads and writes its storage, with no keys anywhere
resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: '${appName}-api-identity'
  location: location
}

resource registry 'Microsoft.ContainerRegistry/registries@2025-04-01' = {
  name: '${appName}acr${suffix}'
  location: location
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
  }
}

resource logs 'Microsoft.OperationalInsights/workspaces@2025-02-01' = {
  name: '${appName}-logs'
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

resource environment 'Microsoft.App/managedEnvironments@2025-01-01' = {
  name: '${appName}-env'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

// Role-based access only. Deleted vaults stay recoverable for 7 days; teardown.ps1 purges them, so setup.ps1 can
// create the same name again.
resource vault 'Microsoft.KeyVault/vaults@2024-11-01' = {
  name: '${appName}kv${suffix}'
  location: location
  properties: {
    tenantId: subscription().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    softDeleteRetentionInDays: 7
  }
}

// Signed-in access only: no account keys and no public blobs. The API serves the files itself.
resource storage 'Microsoft.Storage/storageAccounts@2025-01-01' = {
  name: '${appName}st${suffix}'
  location: location
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2025-01-01' = {
  parent: storage
  name: 'default'
}

resource uploads 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-01-01' = {
  parent: blobService
  name: 'uploads'
  properties: {
    publicAccess: 'None'
  }
}

resource tableService 'Microsoft.Storage/storageAccounts/tableServices@2025-01-01' = {
  parent: storage
  name: 'default'
}

resource receipts 'Microsoft.Storage/storageAccounts/tableServices/tables@2025-01-01' = {
  parent: tableService
  name: 'receipts'
}

resource uploadCounts 'Microsoft.Storage/storageAccounts/tableServices/tables@2025-01-01' = {
  parent: tableService
  name: 'uploadcounts'
}

// The app's identity: its container, its two tables and pulling images. setup.ps1 grants it the Gemini key's secret
// once the secret exists, since a role can't be scoped to a secret that isn't there yet.
resource appPullsImages 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, identity.id, roles.acrPull)
  scope: registry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPull)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource appWritesUploads 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(uploads.id, identity.id, roles.blobDataContributor)
  scope: uploads
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.blobDataContributor)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource appWritesReceipts 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(receipts.id, identity.id, roles.tableDataContributor)
  scope: receipts
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.tableDataContributor)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource appWritesUploadCounts 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(uploadCounts.id, identity.id, roles.tableDataContributor)
  scope: uploadCounts
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.tableDataContributor)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// The deploy workflow: push images, create or update the Container App with the app's identity, and read this
// deployment's outputs. Nothing outside this resource group, no stored data and no role assignments.
resource deployPushesImages 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, deployPrincipalId, roles.acrPush)
  scope: registry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPush)
    principalId: deployPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource deployManagesContainerApps 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, deployPrincipalId, roles.containerAppsContributor)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.containerAppsContributor)
    principalId: deployPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource deployAssignsTheAppIdentity 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(identity.id, deployPrincipalId, roles.managedIdentityOperator)
  scope: identity
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.managedIdentityOperator)
    principalId: deployPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource deployReadsTheResourceGroup 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, deployPrincipalId, roles.reader)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.reader)
    principalId: deployPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// Whoever runs setup.ps1 stores the Gemini key
resource operatorWritesSecrets 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(vault.id, operatorPrincipalId, roles.keyVaultSecretsOfficer)
  scope: vault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.keyVaultSecretsOfficer)
    principalId: operatorPrincipalId
    principalType: 'User'
  }
}

output registryName string = registry.name
output registryLoginServer string = registry.properties.loginServer
output identityId string = identity.id
output identityClientId string = identity.properties.clientId
output identityPrincipalId string = identity.properties.principalId
output environmentId string = environment.id
output storageAccount string = storage.name
output keyVaultId string = vault.id
output keyVaultName string = vault.name
output keyVaultUrl string = vault.properties.vaultUri
