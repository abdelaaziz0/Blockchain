"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                     NFT MARKETPLACE - SMART CONTRACT                         ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  FONCTIONNALITÉS COMPLÈTES:                                                  ║
║  ✓ Mint NFTs avec métadonnées et royalties configurables                    ║
║  ✓ Listing/Achat/Annulation de ventes                                       ║
║  ✓ Système d'offres (make/cancel/accept)                                    ║
║  ✓ Transfert et Burn sécurisés                                              ║
║  ✓ Pull pattern pour paiements (reentrancy safe)                            ║
║  ✓ Administration avec changement d'admin en 2 étapes                       ║
║  ✓ Configuration modifiable (fees, prices)                                  ║
║  ✓ Événements pour indexation off-chain                                     ║
║  ✓ Vues onchain complètes                                                   ║
║  ✓ Protection burn address                                                  ║
║  ✓ Pause d'urgence                                                          ║
║  ✓ Limite de supply                                                         ║
║  ✓ Tests                                                                    ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import smartpy as sp


@sp.module
def main():
    """Module principal du NFT Marketplace"""
    
    # ═══════════════════════════════════════════════════════════════════════════
    # TYPES
    # ═══════════════════════════════════════════════════════════════════════════
    
    token_type: type = sp.record(
        metadata=sp.string,
        author=sp.address,
        owner=sp.address,
        price=sp.mutez,
        for_sale=sp.bool,
        royalty_percent=sp.nat,
        created_at=sp.timestamp
    )
    
    offer_type: type = sp.record(
        amount=sp.mutez,
        expires_at=sp.timestamp
    )
    
    # ═══════════════════════════════════════════════════════════════════════════
    # CONTRAT
    # ═══════════════════════════════════════════════════════════════════════════
    
    class NFTMarketplace(sp.Contract):
        """
        NFT Marketplace complet et sécurisé pour Tezos.
        
        Sécurité:
        - Pull pattern pour tous les paiements
        - Protection contre reentrancy
        - Protection burn address
        - Vérifications exhaustives
        - Pause d'urgence
        """
        
        def __init__(
            self,
            admin: sp.address,
            platform_fee_percent: sp.nat,
            mint_price: sp.mutez,
            min_sale_price: sp.mutez,
            max_metadata_length: sp.nat,
            max_supply: sp.nat
        ):
            """
            Initialise le marketplace.
            
            Args:
                admin: Adresse administrateur
                platform_fee_percent: Frais plateforme (0-20%)
                mint_price: Prix de mint en mutez
                min_sale_price: Prix minimum de vente
                max_metadata_length: Longueur max des métadonnées
                max_supply: Supply max (0 = illimité)
            """
            # Validations initiales
            assert platform_fee_percent <= sp.nat(20), "INIT: Fee too high"
            assert max_metadata_length >= sp.nat(10), "INIT: Metadata length too small"
            
            # Storage principal
            self.data.tokens = sp.cast(sp.big_map(), sp.big_map[sp.nat, token_type])
            self.data.next_id = sp.nat(0)
            
            # Offres: token_id -> (buyer -> offer)
            self.data.offers = sp.cast(
                sp.big_map(),
                sp.big_map[sp.nat, sp.map[sp.address, offer_type]]
            )
            
            # Paiements en attente (pull pattern)
            self.data.pending_payments = sp.cast(
                sp.big_map(),
                sp.big_map[sp.address, sp.mutez]
            )
            
            # Frais collectés
            self.data.collected_fees = sp.mutez(0)
            
            # Administration
            self.data.admin = admin
            self.data.pending_admin = sp.cast(None, sp.option[sp.address])
            
            # Configuration
            self.data.platform_fee_percent = platform_fee_percent
            self.data.mint_price = mint_price
            self.data.min_sale_price = min_sale_price
            self.data.max_metadata_length = max_metadata_length
            self.data.max_supply = max_supply
            
            # État
            self.data.paused = False
        
        # ═══════════════════════════════════════════════════════════════════════
        # FONCTIONS PRIVÉES
        # ═══════════════════════════════════════════════════════════════════════
        
        @sp.private(with_storage="read-write")
        def _add_pending(self, params):
            """Ajoute un paiement en attente de manière sécurisée."""
            recipient = params.recipient
            amount = params.amount
            if amount > sp.mutez(0):
                if recipient in self.data.pending_payments:
                    self.data.pending_payments[recipient] += amount
                else:
                    self.data.pending_payments[recipient] = amount
        
        # ═══════════════════════════════════════════════════════════════════════
        # MINTING
        # ═══════════════════════════════════════════════════════════════════════
        
        @sp.entrypoint
        def mint(self, metadata: sp.string, royalty_percent: sp.nat):
            """
            Crée un nouveau NFT.
            
            Args:
                metadata: URI IPFS ou données JSON
                royalty_percent: Pourcentage de royalties (0-50%)
            
            Requires:
                - Contrat non pausé
                - Montant exact = mint_price
                - Métadonnées non vides et <= max_length
                - Royalties <= 50%
                - Supply non atteinte
            """
            # Vérifications
            assert not self.data.paused, "MINT: Contract paused"
            assert sp.amount == self.data.mint_price, "MINT: Invalid amount"
            assert sp.len(metadata) > sp.nat(0), "MINT: Empty metadata"
            assert sp.len(metadata) <= self.data.max_metadata_length, "MINT: Metadata too long"
            assert royalty_percent <= sp.nat(50), "MINT: Royalty too high"
            
            # Vérifier supply
            if self.data.max_supply > sp.nat(0):
                assert self.data.next_id < self.data.max_supply, "MINT: Max supply reached"
            
            # Créer le token
            token_id = self.data.next_id
            self.data.tokens[token_id] = sp.record(
                metadata=metadata,
                author=sp.sender,
                owner=sp.sender,
                price=sp.mutez(0),
                for_sale=False,
                royalty_percent=royalty_percent,
                created_at=sp.now
            )
            
            self.data.next_id += 1
            self.data.collected_fees += sp.amount
            
            # Événement
            sp.emit(sp.record(
                token_id=token_id,
                author=sp.sender,
                metadata=metadata,
                royalty=royalty_percent
            ), tag="Mint")
        
        # ═══════════════════════════════════════════════════════════════════════
        # LISTING
        # ═══════════════════════════════════════════════════════════════════════
        
        @sp.entrypoint
        def list_for_sale(self, token_id: sp.nat, price: sp.mutez):
            """
            Met un NFT en vente.
            
            Args:
                token_id: ID du token
                price: Prix de vente
            
            Requires:
                - Pas de tez envoyé
                - Token existe
                - Appelant est propriétaire
                - Token pas déjà en vente
                - Prix >= min_sale_price
            """
            assert not self.data.paused, "LIST: Contract paused"
            assert sp.amount == sp.mutez(0), "LIST: No tez expected"
            assert token_id in self.data.tokens, "LIST: Token not found"
            assert price >= self.data.min_sale_price, "LIST: Price below minimum"
            
            token = self.data.tokens[token_id]
            assert token.owner == sp.sender, "LIST: Not owner"
            assert not token.for_sale, "LIST: Already listed"
            
            token.price = price
            token.for_sale = True
            self.data.tokens[token_id] = token
            
            sp.emit(sp.record(
                token_id=token_id,
                seller=sp.sender,
                price=price
            ), tag="Listed")
        
        @sp.entrypoint
        def update_price(self, token_id: sp.nat, new_price: sp.mutez):
            """Met à jour le prix d'un token en vente."""
            assert not self.data.paused, "UPDATE: Contract paused"
            assert sp.amount == sp.mutez(0), "UPDATE: No tez expected"
            assert token_id in self.data.tokens, "UPDATE: Token not found"
            assert new_price >= self.data.min_sale_price, "UPDATE: Price below minimum"
            
            token = self.data.tokens[token_id]
            assert token.owner == sp.sender, "UPDATE: Not owner"
            assert token.for_sale, "UPDATE: Not listed"
            
            old_price = token.price
            token.price = new_price
            self.data.tokens[token_id] = token
            
            sp.emit(sp.record(
                token_id=token_id,
                old_price=old_price,
                new_price=new_price
            ), tag="PriceUpdated")
        
        @sp.entrypoint
        def cancel_sale(self, token_id: sp.nat):
            """Annule la mise en vente d'un NFT."""
            assert sp.amount == sp.mutez(0), "CANCEL: No tez expected"
            assert token_id in self.data.tokens, "CANCEL: Token not found"
            
            token = self.data.tokens[token_id]
            assert token.owner == sp.sender, "CANCEL: Not owner"
            assert token.for_sale, "CANCEL: Not listed"
            
            token.for_sale = False
            token.price = sp.mutez(0)
            self.data.tokens[token_id] = token
            
            sp.emit(sp.record(token_id=token_id, seller=sp.sender), tag="Cancelled")
        
        # ═══════════════════════════════════════════════════════════════════════
        # ACHAT
        # ═══════════════════════════════════════════════════════════════════════
        
        @sp.entrypoint
        def buy(self, token_id: sp.nat):
            """
            Achète un NFT en vente.
            
            Distribution:
            - Royalties à l'auteur (si différent du vendeur)
            - Frais de plateforme
            - Reste au vendeur
            
            Tous les paiements vont en pending (pull pattern).
            """
            assert not self.data.paused, "BUY: Contract paused"
            assert token_id in self.data.tokens, "BUY: Token not found"
            
            token = self.data.tokens[token_id]
            assert token.for_sale, "BUY: Not for sale"
            assert sp.sender != token.owner, "BUY: Cannot buy own token"
            assert sp.amount == token.price, "BUY: Wrong amount"
            
            # Calculer distribution
            royalty = sp.split_tokens(token.price, token.royalty_percent, sp.nat(100))
            fee = sp.split_tokens(token.price, self.data.platform_fee_percent, sp.nat(100))
            seller_amount = token.price - royalty - fee
            
            # Sauvegarder avant modification
            author_addr = token.author
            seller_addr = token.owner
            sale_price = token.price
            
            # Transférer propriété
            token.owner = sp.sender
            token.for_sale = False
            token.price = sp.mutez(0)
            self.data.tokens[token_id] = token
            
            # Distribuer (pull pattern)
            self.data.collected_fees += fee
            
            if author_addr != seller_addr:
                self._add_pending(sp.record(recipient=author_addr, amount=royalty))
                self._add_pending(sp.record(recipient=seller_addr, amount=seller_amount))
            else:
                # Auteur = vendeur: combine les deux
                self._add_pending(sp.record(recipient=seller_addr, amount=seller_amount + royalty))
            
            sp.emit(sp.record(
                token_id=token_id,
                seller=seller_addr,
                buyer=sp.sender,
                price=sale_price,
                royalty=royalty,
                fee=fee
            ), tag="Sale")
        
        # ═══════════════════════════════════════════════════════════════════════
        # OFFRES
        # ═══════════════════════════════════════════════════════════════════════
        
        @sp.entrypoint
        def make_offer(self, token_id: sp.nat, duration_seconds: sp.int):
            """
            Fait une offre sur un NFT (même non listé).
            
            Args:
                token_id: ID du token
                duration_seconds: Durée de validité en secondes
            
            Le montant de l'offre = tez envoyés.
            """
            assert not self.data.paused, "OFFER: Contract paused"
            assert token_id in self.data.tokens, "OFFER: Token not found"
            assert duration_seconds > 0, "OFFER: Invalid duration"
            assert sp.amount >= self.data.min_sale_price, "OFFER: Amount too low"
            
            token = self.data.tokens[token_id]
            assert sp.sender != token.owner, "OFFER: Cannot offer on own token"
            
            # Créer l'offre
            new_offer = sp.record(
                amount=sp.amount,
                expires_at=sp.add_seconds(sp.now, duration_seconds)
            )
            
            # Rembourser ancienne offre si existe
            if token_id in self.data.offers:
                token_offers = self.data.offers[token_id]
                if sp.sender in token_offers:
                    old_offer = token_offers[sp.sender]
                    self._add_pending(sp.record(recipient=sp.sender, amount=old_offer.amount))
                token_offers[sp.sender] = new_offer
                self.data.offers[token_id] = token_offers
            else:
                # Créer nouvelle map d'offres pour ce token
                empty_map = sp.cast({}, sp.map[sp.address, offer_type])
                empty_map[sp.sender] = new_offer
                self.data.offers[token_id] = empty_map
            
            sp.emit(sp.record(
                token_id=token_id,
                buyer=sp.sender,
                amount=sp.amount,
                expires_at=new_offer.expires_at
            ), tag="OfferMade")
        
        @sp.entrypoint
        def cancel_offer(self, token_id: sp.nat):
            """Annule une offre et rembourse via pending."""
            assert sp.amount == sp.mutez(0), "CANCEL_OFFER: No tez expected"
            assert token_id in self.data.offers, "CANCEL_OFFER: No offers on token"
            
            token_offers = self.data.offers[token_id]
            assert sp.sender in token_offers, "CANCEL_OFFER: No offer from you"
            
            offer = token_offers[sp.sender]
            del token_offers[sp.sender]
            self.data.offers[token_id] = token_offers
            
            self._add_pending(sp.record(recipient=sp.sender, amount=offer.amount))
            
            sp.emit(sp.record(
                token_id=token_id,
                buyer=sp.sender,
                refunded=offer.amount
            ), tag="OfferCancelled")
        
        @sp.entrypoint
        def accept_offer(self, token_id: sp.nat, buyer: sp.address):
            """
            Accepte une offre sur un NFT.
            
            Args:
                token_id: ID du token
                buyer: Adresse de l'acheteur dont on accepte l'offre
            """
            assert not self.data.paused, "ACCEPT: Contract paused"
            assert sp.amount == sp.mutez(0), "ACCEPT: No tez expected"
            assert token_id in self.data.tokens, "ACCEPT: Token not found"
            assert token_id in self.data.offers, "ACCEPT: No offers"
            
            token = self.data.tokens[token_id]
            assert token.owner == sp.sender, "ACCEPT: Not owner"
            
            token_offers = self.data.offers[token_id]
            assert buyer in token_offers, "ACCEPT: Offer not found"
            
            offer = token_offers[buyer]
            assert sp.now < offer.expires_at, "ACCEPT: Offer expired"
            
            # Calculer distribution
            royalty = sp.split_tokens(offer.amount, token.royalty_percent, sp.nat(100))
            fee = sp.split_tokens(offer.amount, self.data.platform_fee_percent, sp.nat(100))
            seller_amount = offer.amount - royalty - fee
            
            author_addr = token.author
            seller_addr = token.owner
            
            # Si token était en vente, retirer
            token.owner = buyer
            token.for_sale = False
            token.price = sp.mutez(0)
            self.data.tokens[token_id] = token
            
            # Supprimer l'offre
            del token_offers[buyer]
            self.data.offers[token_id] = token_offers
            
            # Distribuer
            self.data.collected_fees += fee
            if author_addr != seller_addr:
                self._add_pending(sp.record(recipient=author_addr, amount=royalty))
                self._add_pending(sp.record(recipient=seller_addr, amount=seller_amount))
            else:
                self._add_pending(sp.record(recipient=seller_addr, amount=seller_amount + royalty))
            
            sp.emit(sp.record(
                token_id=token_id,
                seller=seller_addr,
                buyer=buyer,
                price=offer.amount
            ), tag="OfferAccepted")
        
        # ═══════════════════════════════════════════════════════════════════════
        # TRANSFERT & BURN
        # ═══════════════════════════════════════════════════════════════════════
        
        @sp.entrypoint
        def transfer(self, token_id: sp.nat, to_: sp.address):
            """
            Transfère un NFT gratuitement.
            
            Requires:
                - Token non listé
                - Appelant est propriétaire
                - Destination n'est pas burn address
            """
            assert not self.data.paused, "TRANSFER: Contract paused"
            assert sp.amount == sp.mutez(0), "TRANSFER: No tez expected"
            assert token_id in self.data.tokens, "TRANSFER: Token not found"
            assert to_ != sp.address("tz1Ke2h7sDdakHJQh8WX4Z372du1KChsksyU"), "TRANSFER: Cannot send to burn address"
            assert to_ != sp.sender, "TRANSFER: Cannot transfer to self"
            
            token = self.data.tokens[token_id]
            assert token.owner == sp.sender, "TRANSFER: Not owner"
            assert not token.for_sale, "TRANSFER: Token is listed"
            
            old_owner = token.owner
            token.owner = to_
            self.data.tokens[token_id] = token
            
            sp.emit(sp.record(
                token_id=token_id,
                from_=old_owner,
                to_=to_
            ), tag="Transfer")
        
        @sp.entrypoint
        def burn(self, token_id: sp.nat):
            """
            Détruit un NFT définitivement.
            
            Rembourse toutes les offres en cours.
            """
            assert sp.amount == sp.mutez(0), "BURN: No tez expected"
            assert token_id in self.data.tokens, "BURN: Token not found"
            
            token = self.data.tokens[token_id]
            assert token.owner == sp.sender, "BURN: Not owner"
            assert not token.for_sale, "BURN: Token is listed"
            
            # Supprimer le token
            del self.data.tokens[token_id]
            
            # Rembourser toutes les offres
            if token_id in self.data.offers:
                token_offers = self.data.offers[token_id]
                for buyer_addr in token_offers.keys():
                    offer = token_offers[buyer_addr]
                    self._add_pending(sp.record(recipient=buyer_addr, amount=offer.amount))
                del self.data.offers[token_id]
            
            sp.emit(sp.record(
                token_id=token_id,
                owner=sp.sender
            ), tag="Burn")
        
        # ═══════════════════════════════════════════════════════════════════════
        # RETRAITS
        # ═══════════════════════════════════════════════════════════════════════
        
        @sp.entrypoint
        def withdraw(self):
            """Retire les paiements en attente."""
            assert sp.amount == sp.mutez(0), "WITHDRAW: No tez expected"
            assert sp.sender in self.data.pending_payments, "WITHDRAW: Nothing pending"
            
            amount = self.data.pending_payments[sp.sender]
            assert amount > sp.mutez(0), "WITHDRAW: Zero amount"
            
            # Supprimer AVANT d'envoyer (reentrancy protection)
            del self.data.pending_payments[sp.sender]
            sp.send(sp.sender, amount)
            
            sp.emit(sp.record(
                recipient=sp.sender,
                amount=amount
            ), tag="Withdrawal")
        
        @sp.entrypoint
        def withdraw_fees(self):
            """Retire les frais collectés (admin only)."""
            assert sp.amount == sp.mutez(0), "FEES: No tez expected"
            assert sp.sender == self.data.admin, "FEES: Not admin"
            assert self.data.collected_fees > sp.mutez(0), "FEES: Nothing to withdraw"
            
            amount = self.data.collected_fees
            self.data.collected_fees = sp.mutez(0)
            sp.send(self.data.admin, amount)
            
            sp.emit(sp.record(
                admin=self.data.admin,
                amount=amount
            ), tag="FeesWithdrawn")
        
        # ═══════════════════════════════════════════════════════════════════════
        # ADMINISTRATION
        # ═══════════════════════════════════════════════════════════════════════
        
        @sp.entrypoint
        def set_pause(self, paused: sp.bool):
            """Active/désactive la pause."""
            assert sp.amount == sp.mutez(0), "PAUSE: No tez expected"
            assert sp.sender == self.data.admin, "PAUSE: Not admin"
            self.data.paused = paused
            sp.emit(sp.record(paused=paused), tag="PauseChanged")
        
        @sp.entrypoint
        def propose_admin(self, new_admin: sp.address):
            """Propose un nouvel admin (étape 1)."""
            assert sp.amount == sp.mutez(0), "ADMIN: No tez expected"
            assert sp.sender == self.data.admin, "ADMIN: Not admin"
            assert new_admin != self.data.admin, "ADMIN: Same admin"
            self.data.pending_admin = sp.Some(new_admin)
            sp.emit(sp.record(proposed=new_admin), tag="AdminProposed")
        
        @sp.entrypoint
        def accept_admin(self):
            """Accepte le rôle d'admin (étape 2)."""
            assert sp.amount == sp.mutez(0), "ADMIN: No tez expected"
            pending = self.data.pending_admin.unwrap_some(error="ADMIN: No pending")
            assert sp.sender == pending, "ADMIN: Not proposed admin"
            
            old_admin = self.data.admin
            self.data.admin = pending
            self.data.pending_admin = None
            
            sp.emit(sp.record(
                old_admin=old_admin,
                new_admin=pending
            ), tag="AdminChanged")
        
        @sp.entrypoint
        def cancel_admin_change(self):
            """Annule le changement d'admin en cours."""
            assert sp.amount == sp.mutez(0), "ADMIN: No tez expected"
            assert sp.sender == self.data.admin, "ADMIN: Not admin"
            self.data.pending_admin = None
            sp.emit(sp.record(cancelled=True), tag="AdminChangeCancelled")
        
        @sp.entrypoint
        def update_platform_fee(self, new_fee: sp.nat):
            """Met à jour les frais de plateforme."""
            assert sp.amount == sp.mutez(0), "FEE: No tez expected"
            assert sp.sender == self.data.admin, "FEE: Not admin"
            assert new_fee <= sp.nat(20), "FEE: Too high"
            self.data.platform_fee_percent = new_fee
            sp.emit(sp.record(new_fee=new_fee), tag="FeeUpdated")
        
        @sp.entrypoint
        def update_mint_price(self, new_price: sp.mutez):
            """Met à jour le prix de mint."""
            assert sp.amount == sp.mutez(0), "PRICE: No tez expected"
            assert sp.sender == self.data.admin, "PRICE: Not admin"
            self.data.mint_price = new_price
            sp.emit(sp.record(new_price=new_price), tag="MintPriceUpdated")
        
        @sp.entrypoint
        def update_min_sale_price(self, new_price: sp.mutez):
            """Met à jour le prix minimum de vente."""
            assert sp.amount == sp.mutez(0), "PRICE: No tez expected"
            assert sp.sender == self.data.admin, "PRICE: Not admin"
            self.data.min_sale_price = new_price
            sp.emit(sp.record(new_price=new_price), tag="MinSalePriceUpdated")
        
        # ═══════════════════════════════════════════════════════════════════════
        # VUES ONCHAIN
        # ═══════════════════════════════════════════════════════════════════════
        
        @sp.onchain_view
        def get_token(self, token_id: sp.nat) -> token_type:
            """Retourne les données complètes d'un token."""
            assert token_id in self.data.tokens, "VIEW: Token not found"
            return self.data.tokens[token_id]
        
        @sp.onchain_view
        def get_owner(self, token_id: sp.nat) -> sp.address:
            """Retourne le propriétaire d'un token."""
            assert token_id in self.data.tokens, "VIEW: Token not found"
            return self.data.tokens[token_id].owner
        
        @sp.onchain_view
        def is_for_sale(self, token_id: sp.nat) -> sp.bool:
            """Vérifie si un token est en vente."""
            result = False
            if token_id in self.data.tokens:
                result = self.data.tokens[token_id].for_sale
            return result
        
        @sp.onchain_view
        def get_price(self, token_id: sp.nat) -> sp.mutez:
            """Retourne le prix (0 si non listé)."""
            result = sp.mutez(0)
            if token_id in self.data.tokens:
                token = self.data.tokens[token_id]
                if token.for_sale:
                    result = token.price
            return result
        
        @sp.onchain_view
        def get_pending(self, addr: sp.address) -> sp.mutez:
            """Retourne le montant en attente."""
            result = sp.mutez(0)
            if addr in self.data.pending_payments:
                result = self.data.pending_payments[addr]
            return result
        
        @sp.onchain_view
        def get_total_supply(self) -> sp.nat:
            """Retourne le nombre total de tokens créés."""
            return self.data.next_id
        
        @sp.onchain_view
        def get_admin(self) -> sp.address:
            """Retourne l'adresse admin."""
            return self.data.admin
        
        @sp.onchain_view
        def is_paused(self) -> sp.bool:
            """Vérifie si le contrat est en pause."""
            return self.data.paused
        
        @sp.onchain_view
        def get_config(self) -> sp.record(
            platform_fee=sp.nat,
            mint_price=sp.mutez,
            min_sale_price=sp.mutez,
            max_supply=sp.nat
        ):
            """Retourne la configuration."""
            return sp.record(
                platform_fee=self.data.platform_fee_percent,
                mint_price=self.data.mint_price,
                min_sale_price=self.data.min_sale_price,
                max_supply=self.data.max_supply
            )


# ═══════════════════════════════════════════════════════════════════════════════
# TESTS EXHAUSTIFS
# ═══════════════════════════════════════════════════════════════════════════════

# -------------------------------------------------------------------------------
# TEST 1: MINT (tous les cas)
# -------------------------------------------------------------------------------
@sp.add_test()
def test_mint_comprehensive():
    """Tests exhaustifs pour mint()"""
    scenario = sp.test_scenario("Mint_Comprehensive", main)
    scenario.h1("MINT - Tests Exhaustifs")
    
    admin = sp.test_account("admin")
    alice = sp.test_account("alice")
    bob = sp.test_account("bob")
    
    c = main.NFTMarketplace(
        admin=admin.address,
        platform_fee_percent=sp.nat(5),
        mint_price=sp.tez(1),
        min_sale_price=sp.tez(1),
        max_metadata_length=sp.nat(256),
        max_supply=sp.nat(3)
    )
    scenario += c
    
    # SUCCESS 1: Premier mint
    scenario.h2("SUCCESS: Premier mint par Alice")
    c.mint(metadata="ipfs://Qm1", royalty_percent=sp.nat(10),
           _sender=alice, _amount=sp.tez(1))
    scenario.verify(c.data.next_id == 1)
    scenario.verify(c.data.tokens[0].owner == alice.address)
    scenario.verify(c.data.tokens[0].author == alice.address)
    scenario.verify(c.data.tokens[0].royalty_percent == 10)
    scenario.verify(c.data.collected_fees == sp.tez(1))
    
    # SUCCESS 2: Second mint par Bob
    scenario.h2("SUCCESS: Second mint par Bob")
    c.mint(metadata="ipfs://Qm2", royalty_percent=sp.nat(0),
           _sender=bob, _amount=sp.tez(1))
    scenario.verify(c.data.next_id == 2)
    scenario.verify(c.data.tokens[1].owner == bob.address)
    
    # FAIL 1: Montant incorrect (trop)
    scenario.h2("FAIL: Montant trop élevé")
    c.mint(metadata="ipfs://Qm3", royalty_percent=sp.nat(5),
           _sender=alice, _amount=sp.tez(2),
           _valid=False, _exception="MINT: Invalid amount")
    
    # FAIL 2: Montant incorrect (pas assez)
    scenario.h2("FAIL: Montant insuffisant")
    c.mint(metadata="ipfs://Qm3", royalty_percent=sp.nat(5),
           _sender=alice, _amount=sp.mutez(500000),
           _valid=False, _exception="MINT: Invalid amount")
    
    # FAIL 3: Métadonnées vides
    scenario.h2("FAIL: Métadonnées vides")
    c.mint(metadata="", royalty_percent=sp.nat(5),
           _sender=alice, _amount=sp.tez(1),
           _valid=False, _exception="MINT: Empty metadata")
    
    # FAIL 4: Métadonnées trop longues
    scenario.h2("FAIL: Métadonnées trop longues")
    long_metadata = "x" * 300  # > 256
    c.mint(metadata=long_metadata, royalty_percent=sp.nat(5),
           _sender=alice, _amount=sp.tez(1),
           _valid=False, _exception="MINT: Metadata too long")
    
    # FAIL 5: Royalties trop élevées
    scenario.h2("FAIL: Royalties > 50%")
    c.mint(metadata="ipfs://Qm3", royalty_percent=sp.nat(51),
           _sender=alice, _amount=sp.tez(1),
           _valid=False, _exception="MINT: Royalty too high")
    
    # SUCCESS 3: Troisième mint (dernière place)
    scenario.h2("SUCCESS: Troisième mint (supply=3)")
    c.mint(metadata="ipfs://Qm3", royalty_percent=sp.nat(25),
           _sender=alice, _amount=sp.tez(1))
    scenario.verify(c.data.next_id == 3)
    
    # FAIL 6: Supply max atteinte
    scenario.h2("FAIL: Max supply atteinte")
    c.mint(metadata="ipfs://Qm4", royalty_percent=sp.nat(5),
           _sender=alice, _amount=sp.tez(1),
           _valid=False, _exception="MINT: Max supply reached")
    
    # FAIL 7: Mint quand pausé
    scenario.h2("FAIL: Mint quand pausé")
    c.set_pause(True, _sender=admin)
    c.mint(metadata="ipfs://Qm5", royalty_percent=sp.nat(5),
           _sender=bob, _amount=sp.tez(1),
           _valid=False, _exception="MINT: Contract paused")
    c.set_pause(False, _sender=admin)


# -------------------------------------------------------------------------------
# TEST 2: LIST_FOR_SALE (tous les cas)
# -------------------------------------------------------------------------------
@sp.add_test()
def test_list_comprehensive():
    """Tests exhaustifs pour list_for_sale()"""
    scenario = sp.test_scenario("List_Comprehensive", main)
    scenario.h1("LIST_FOR_SALE - Tests Exhaustifs")
    
    admin = sp.test_account("admin")
    alice = sp.test_account("alice")
    bob = sp.test_account("bob")
    
    c = main.NFTMarketplace(
        admin=admin.address,
        platform_fee_percent=sp.nat(5),
        mint_price=sp.tez(1),
        min_sale_price=sp.tez(2),
        max_metadata_length=sp.nat(256),
        max_supply=sp.nat(0)
    )
    scenario += c
    
    # Setup: mint 2 tokens
    c.mint(metadata="ipfs://Qm1", royalty_percent=sp.nat(10),
           _sender=alice, _amount=sp.tez(1))
    c.mint(metadata="ipfs://Qm2", royalty_percent=sp.nat(5),
           _sender=bob, _amount=sp.tez(1))
    
    # SUCCESS 1: List token 0
    scenario.h2("SUCCESS: Alice liste token 0")
    c.list_for_sale(token_id=sp.nat(0), price=sp.tez(10), _sender=alice)
    scenario.verify(c.data.tokens[0].for_sale == True)
    scenario.verify(c.data.tokens[0].price == sp.tez(10))
    
    # SUCCESS 2: List token 1
    scenario.h2("SUCCESS: Bob liste token 1")
    c.list_for_sale(token_id=sp.nat(1), price=sp.tez(5), _sender=bob)
    scenario.verify(c.data.tokens[1].for_sale == True)
    
    # FAIL 1: Pas propriétaire
    scenario.h2("FAIL: Bob essaie de lister token d'Alice")
    c.cancel_sale(sp.nat(0), _sender=alice)  # D'abord delist
    c.list_for_sale(token_id=sp.nat(0), price=sp.tez(10),
                    _sender=bob, _valid=False, _exception="LIST: Not owner")
    
    # FAIL 2: Token déjà listé
    scenario.h2("FAIL: Token déjà listé")
    c.list_for_sale(token_id=sp.nat(0), price=sp.tez(10), _sender=alice)
    c.list_for_sale(token_id=sp.nat(0), price=sp.tez(20),
                    _sender=alice, _valid=False, _exception="LIST: Already listed")
    
    # FAIL 3: Token inexistant
    scenario.h2("FAIL: Token inexistant")
    c.list_for_sale(token_id=sp.nat(999), price=sp.tez(10),
                    _sender=alice, _valid=False, _exception="LIST: Token not found")
    
    # FAIL 4: Prix trop bas
    scenario.h2("FAIL: Prix < min_sale_price")
    c.cancel_sale(sp.nat(0), _sender=alice)
    c.list_for_sale(token_id=sp.nat(0), price=sp.tez(1),
                    _sender=alice, _valid=False, _exception="LIST: Price below minimum")
    
    # FAIL 5: Tez envoyés
    scenario.h2("FAIL: Tez envoyés avec list")
    c.list_for_sale(token_id=sp.nat(0), price=sp.tez(10),
                    _sender=alice, _amount=sp.tez(1),
                    _valid=False, _exception="LIST: No tez expected")
    
    # FAIL 6: Contrat pausé
    scenario.h2("FAIL: List quand pausé")
    c.set_pause(True, _sender=admin)
    c.list_for_sale(token_id=sp.nat(0), price=sp.tez(10),
                    _sender=alice, _valid=False, _exception="LIST: Contract paused")
    c.set_pause(False, _sender=admin)


# -------------------------------------------------------------------------------
# TEST 3: UPDATE_PRICE (tous les cas)
# -------------------------------------------------------------------------------
@sp.add_test()
def test_update_price_comprehensive():
    """Tests exhaustifs pour update_price()"""
    scenario = sp.test_scenario("UpdatePrice_Comprehensive", main)
    scenario.h1("UPDATE_PRICE - Tests Exhaustifs")
    
    admin = sp.test_account("admin")
    alice = sp.test_account("alice")
    bob = sp.test_account("bob")
    
    c = main.NFTMarketplace(
        admin=admin.address,
        platform_fee_percent=sp.nat(5),
        mint_price=sp.tez(1),
        min_sale_price=sp.tez(2),
        max_metadata_length=sp.nat(256),
        max_supply=sp.nat(0)
    )
    scenario += c
    
    c.mint(metadata="ipfs://Qm1", royalty_percent=sp.nat(10),
           _sender=alice, _amount=sp.tez(1))
    c.list_for_sale(token_id=sp.nat(0), price=sp.tez(10), _sender=alice)
    
    # SUCCESS 1: Update prix
    scenario.h2("SUCCESS: Update prix à 20 tez")
    c.update_price(token_id=sp.nat(0), new_price=sp.tez(20), _sender=alice)
    scenario.verify(c.data.tokens[0].price == sp.tez(20))
    
    # SUCCESS 2: Update prix encore
    scenario.h2("SUCCESS: Update prix à 5 tez")
    c.update_price(token_id=sp.nat(0), new_price=sp.tez(5), _sender=alice)
    scenario.verify(c.data.tokens[0].price == sp.tez(5))
    
    # FAIL 1: Pas propriétaire
    scenario.h2("FAIL: Bob essaie d'update")
    c.update_price(token_id=sp.nat(0), new_price=sp.tez(100),
                   _sender=bob, _valid=False, _exception="UPDATE: Not owner")
    
    # FAIL 2: Token non listé
    scenario.h2("FAIL: Token non listé")
    c.mint(metadata="ipfs://Qm2", royalty_percent=sp.nat(5),
           _sender=bob, _amount=sp.tez(1))
    c.update_price(token_id=sp.nat(1), new_price=sp.tez(10),
                   _sender=bob, _valid=False, _exception="UPDATE: Not listed")
    
    # FAIL 3: Prix trop bas
    scenario.h2("FAIL: Prix < minimum")
    c.update_price(token_id=sp.nat(0), new_price=sp.tez(1),
                   _sender=alice, _valid=False, _exception="UPDATE: Price below minimum")


# -------------------------------------------------------------------------------
# TEST 4: CANCEL_SALE (tous les cas)
# -------------------------------------------------------------------------------
@sp.add_test()
def test_cancel_sale_comprehensive():
    """Tests exhaustifs pour cancel_sale()"""
    scenario = sp.test_scenario("CancelSale_Comprehensive", main)
    scenario.h1("CANCEL_SALE - Tests Exhaustifs")
    
    admin = sp.test_account("admin")
    alice = sp.test_account("alice")
    bob = sp.test_account("bob")
    
    c = main.NFTMarketplace(
        admin=admin.address,
        platform_fee_percent=sp.nat(5),
        mint_price=sp.tez(1),
        min_sale_price=sp.tez(1),
        max_metadata_length=sp.nat(256),
        max_supply=sp.nat(0)
    )
    scenario += c
    
    c.mint(metadata="ipfs://Qm1", royalty_percent=sp.nat(10),
           _sender=alice, _amount=sp.tez(1))
    c.mint(metadata="ipfs://Qm2", royalty_percent=sp.nat(5),
           _sender=bob, _amount=sp.tez(1))
    c.list_for_sale(token_id=sp.nat(0), price=sp.tez(10), _sender=alice)
    c.list_for_sale(token_id=sp.nat(1), price=sp.tez(5), _sender=bob)
    
    # SUCCESS 1: Cancel par Alice
    scenario.h2("SUCCESS: Alice annule sa vente")
    c.cancel_sale(sp.nat(0), _sender=alice)
    scenario.verify(c.data.tokens[0].for_sale == False)
    scenario.verify(c.data.tokens[0].price == sp.mutez(0))
    
    # SUCCESS 2: Cancel par Bob
    scenario.h2("SUCCESS: Bob annule sa vente")
    c.cancel_sale(sp.nat(1), _sender=bob)
    scenario.verify(c.data.tokens[1].for_sale == False)
    
    # FAIL 1: Pas propriétaire
    scenario.h2("FAIL: Alice essaie d'annuler vente de Bob")
    c.list_for_sale(token_id=sp.nat(1), price=sp.tez(5), _sender=bob)
    c.cancel_sale(sp.nat(1), _sender=alice,
                  _valid=False, _exception="CANCEL: Not owner")
    
    # FAIL 2: Token non listé
    scenario.h2("FAIL: Token non listé")
    c.cancel_sale(sp.nat(0), _sender=alice,
                  _valid=False, _exception="CANCEL: Not listed")
    
    # FAIL 3: Token inexistant
    scenario.h2("FAIL: Token inexistant")
    c.cancel_sale(sp.nat(999), _sender=alice,
                  _valid=False, _exception="CANCEL: Token not found")


# -------------------------------------------------------------------------------
# TEST 5: BUY (tous les cas)
# -------------------------------------------------------------------------------
@sp.add_test()
def test_buy_comprehensive():
    """Tests exhaustifs pour buy()"""
    scenario = sp.test_scenario("Buy_Comprehensive", main)
    scenario.h1("BUY - Tests Exhaustifs")
    
    admin = sp.test_account("admin")
    alice = sp.test_account("alice")
    bob = sp.test_account("bob")
    charlie = sp.test_account("charlie")
    
    c = main.NFTMarketplace(
        admin=admin.address,
        platform_fee_percent=sp.nat(5),
        mint_price=sp.tez(1),
        min_sale_price=sp.tez(1),
        max_metadata_length=sp.nat(256),
        max_supply=sp.nat(0)
    )
    scenario += c
    
    c.mint(metadata="ipfs://Qm1", royalty_percent=sp.nat(10),
           _sender=alice, _amount=sp.tez(1))
    c.mint(metadata="ipfs://Qm2", royalty_percent=sp.nat(20),
           _sender=bob, _amount=sp.tez(1))
    c.list_for_sale(token_id=sp.nat(0), price=sp.tez(100), _sender=alice)
    c.list_for_sale(token_id=sp.nat(1), price=sp.tez(50), _sender=bob)
    
    # SUCCESS 1: Bob achète token 0 d'Alice
    scenario.h2("SUCCESS: Bob achète token 0")
    c.buy(sp.nat(0), _sender=bob, _amount=sp.tez(100))
    scenario.verify(c.data.tokens[0].owner == bob.address)
    scenario.verify(c.data.tokens[0].for_sale == False)
    # Distribution: 10% royalty = 10, 5% fee = 5, seller = 85
    # Alice est author ET seller donc: 85 + 10 = 95
    scenario.verify(c.data.pending_payments[alice.address] == sp.tez(95))
    scenario.verify(c.data.collected_fees == sp.tez(2) + sp.tez(5))  # 2 mints + fee
    
    # SUCCESS 2: Charlie achète token 1 de Bob
    scenario.h2("SUCCESS: Charlie achète token 1")
    c.buy(sp.nat(1), _sender=charlie, _amount=sp.tez(50))
    scenario.verify(c.data.tokens[1].owner == charlie.address)
    # 20% royalty = 10, 5% fee = 2.5 (arrondi), seller = reste
    
    # FAIL 1: Acheter son propre token
    scenario.h2("FAIL: Acheter son propre token")
    c.list_for_sale(token_id=sp.nat(0), price=sp.tez(200), _sender=bob)
    c.buy(sp.nat(0), _sender=bob, _amount=sp.tez(200),
          _valid=False, _exception="BUY: Cannot buy own token")
    
    # FAIL 2: Token non en vente
    scenario.h2("FAIL: Token non en vente")
    c.cancel_sale(sp.nat(0), _sender=bob)
    c.buy(sp.nat(0), _sender=charlie, _amount=sp.tez(200),
          _valid=False, _exception="BUY: Not for sale")
    
    # FAIL 3: Mauvais montant (trop)
    scenario.h2("FAIL: Montant trop élevé")
    c.list_for_sale(token_id=sp.nat(0), price=sp.tez(100), _sender=bob)
    c.buy(sp.nat(0), _sender=charlie, _amount=sp.tez(150),
          _valid=False, _exception="BUY: Wrong amount")
    
    # FAIL 4: Mauvais montant (pas assez)
    scenario.h2("FAIL: Montant insuffisant")
    c.buy(sp.nat(0), _sender=charlie, _amount=sp.tez(50),
          _valid=False, _exception="BUY: Wrong amount")
    
    # FAIL 5: Token inexistant
    scenario.h2("FAIL: Token inexistant")
    c.buy(sp.nat(999), _sender=charlie, _amount=sp.tez(100),
          _valid=False, _exception="BUY: Token not found")


# -------------------------------------------------------------------------------
# TEST 6: OFFERS (tous les cas)
# -------------------------------------------------------------------------------
@sp.add_test()
def test_offers_comprehensive():
    """Tests exhaustifs pour make_offer, cancel_offer, accept_offer"""
    scenario = sp.test_scenario("Offers_Comprehensive", main)
    scenario.h1("OFFERS - Tests Exhaustifs")
    
    admin = sp.test_account("admin")
    alice = sp.test_account("alice")
    bob = sp.test_account("bob")
    charlie = sp.test_account("charlie")
    
    c = main.NFTMarketplace(
        admin=admin.address,
        platform_fee_percent=sp.nat(5),
        mint_price=sp.tez(1),
        min_sale_price=sp.tez(1),
        max_metadata_length=sp.nat(256),
        max_supply=sp.nat(0)
    )
    scenario += c
    
    c.mint(metadata="ipfs://Qm1", royalty_percent=sp.nat(10),
           _sender=alice, _amount=sp.tez(1))
    
    # SUCCESS 1: Bob fait une offre
    scenario.h2("SUCCESS: Bob fait une offre de 50 tez")
    c.make_offer(token_id=sp.nat(0), duration_seconds=86400,
                 _sender=bob, _amount=sp.tez(50))
    scenario.verify(c.data.offers.contains(sp.nat(0)))
    
    # SUCCESS 2: Charlie fait une offre
    scenario.h2("SUCCESS: Charlie fait une offre de 60 tez")
    c.make_offer(token_id=sp.nat(0), duration_seconds=86400,
                 _sender=charlie, _amount=sp.tez(60))
    
    # SUCCESS 3: Bob met à jour son offre (remboursement auto)
    scenario.h2("SUCCESS: Bob augmente son offre à 70 tez")
    c.make_offer(token_id=sp.nat(0), duration_seconds=86400,
                 _sender=bob, _amount=sp.tez(70))
    # L'ancienne offre de 50 tez est remboursée en pending
    scenario.verify(c.data.pending_payments[bob.address] == sp.tez(50))
    
    # FAIL 1: Offre sur son propre token
    scenario.h2("FAIL: Offre sur son propre token")
    c.make_offer(token_id=sp.nat(0), duration_seconds=86400,
                 _sender=alice, _amount=sp.tez(100),
                 _valid=False, _exception="OFFER: Cannot offer on own token")
    
    # FAIL 2: Montant trop bas
    scenario.h2("FAIL: Offre trop basse")
    c.make_offer(token_id=sp.nat(0), duration_seconds=86400,
                 _sender=charlie, _amount=sp.mutez(100),
                 _valid=False, _exception="OFFER: Amount too low")
    
    # FAIL 3: Durée invalide
    scenario.h2("FAIL: Durée invalide")
    c.make_offer(token_id=sp.nat(0), duration_seconds=0,
                 _sender=charlie, _amount=sp.tez(100),
                 _valid=False, _exception="OFFER: Invalid duration")
    
    # SUCCESS 4: Cancel offre
    scenario.h2("SUCCESS: Charlie annule son offre")
    c.cancel_offer(sp.nat(0), _sender=charlie)
    scenario.verify(c.data.pending_payments.contains(charlie.address))
    
    # FAIL 4: Cancel offre inexistante
    scenario.h2("FAIL: Cancel offre inexistante")
    c.cancel_offer(sp.nat(0), _sender=charlie,
                   _valid=False, _exception="CANCEL_OFFER: No offer from you")
    
    # SUCCESS 5: Alice accepte l'offre de Bob
    scenario.h2("SUCCESS: Alice accepte l'offre de Bob")
    c.accept_offer(token_id=sp.nat(0), buyer=bob.address, _sender=alice)
    scenario.verify(c.data.tokens[0].owner == bob.address)
    
    # FAIL 5: Accepter offre inexistante
    scenario.h2("FAIL: Accepter offre inexistante")
    c.mint(metadata="ipfs://Qm2", royalty_percent=sp.nat(5),
           _sender=alice, _amount=sp.tez(1))
    c.make_offer(token_id=sp.nat(1), duration_seconds=86400,
                 _sender=charlie, _amount=sp.tez(30))
    c.accept_offer(token_id=sp.nat(1), buyer=bob.address,
                   _sender=alice, _valid=False, _exception="ACCEPT: Offer not found")
    
    # FAIL 6: Accepter pas propriétaire
    scenario.h2("FAIL: Accepter - pas propriétaire")
    c.accept_offer(token_id=sp.nat(1), buyer=charlie.address,
                   _sender=bob, _valid=False, _exception="ACCEPT: Not owner")


# -------------------------------------------------------------------------------
# TEST 7: TRANSFER (tous les cas)
# -------------------------------------------------------------------------------
@sp.add_test()
def test_transfer_comprehensive():
    """Tests exhaustifs pour transfer()"""
    scenario = sp.test_scenario("Transfer_Comprehensive", main)
    scenario.h1("TRANSFER - Tests Exhaustifs")
    
    admin = sp.test_account("admin")
    alice = sp.test_account("alice")
    bob = sp.test_account("bob")
    charlie = sp.test_account("charlie")
    
    c = main.NFTMarketplace(
        admin=admin.address,
        platform_fee_percent=sp.nat(5),
        mint_price=sp.tez(1),
        min_sale_price=sp.tez(1),
        max_metadata_length=sp.nat(256),
        max_supply=sp.nat(0)
    )
    scenario += c
    
    c.mint(metadata="ipfs://Qm1", royalty_percent=sp.nat(10),
           _sender=alice, _amount=sp.tez(1))
    c.mint(metadata="ipfs://Qm2", royalty_percent=sp.nat(5),
           _sender=bob, _amount=sp.tez(1))
    
    # SUCCESS 1: Alice transfère à Bob
    scenario.h2("SUCCESS: Alice transfère à Bob")
    c.transfer(token_id=sp.nat(0), to_=bob.address, _sender=alice)
    scenario.verify(c.data.tokens[0].owner == bob.address)
    scenario.verify(c.data.tokens[0].author == alice.address)  # Author inchangé
    
    # SUCCESS 2: Bob transfère à Charlie
    scenario.h2("SUCCESS: Bob transfère à Charlie")
    c.transfer(token_id=sp.nat(0), to_=charlie.address, _sender=bob)
    scenario.verify(c.data.tokens[0].owner == charlie.address)
    
    # FAIL 1: Pas propriétaire
    scenario.h2("FAIL: Alice n'est plus propriétaire")
    c.transfer(token_id=sp.nat(0), to_=bob.address,
               _sender=alice, _valid=False, _exception="TRANSFER: Not owner")
    
    # FAIL 2: Transfert à soi-même
    scenario.h2("FAIL: Transfert à soi-même")
    c.transfer(token_id=sp.nat(0), to_=charlie.address,
               _sender=charlie, _valid=False, _exception="TRANSFER: Cannot transfer to self")
    
    # FAIL 3: Transfert à burn address
    scenario.h2("FAIL: Transfert à burn address")
    burn = sp.address("tz1Ke2h7sDdakHJQh8WX4Z372du1KChsksyU")
    c.transfer(token_id=sp.nat(0), to_=burn,
               _sender=charlie, _valid=False, _exception="TRANSFER: Cannot send to burn address")
    
    # FAIL 4: Token listé
    scenario.h2("FAIL: Token listé")
    c.list_for_sale(token_id=sp.nat(1), price=sp.tez(10), _sender=bob)
    c.transfer(token_id=sp.nat(1), to_=alice.address,
               _sender=bob, _valid=False, _exception="TRANSFER: Token is listed")
    
    # FAIL 5: Token inexistant
    scenario.h2("FAIL: Token inexistant")
    c.transfer(token_id=sp.nat(999), to_=alice.address,
               _sender=bob, _valid=False, _exception="TRANSFER: Token not found")


# -------------------------------------------------------------------------------
# TEST 8: BURN (tous les cas)
# -------------------------------------------------------------------------------
@sp.add_test()
def test_burn_comprehensive():
    """Tests exhaustifs pour burn()"""
    scenario = sp.test_scenario("Burn_Comprehensive", main)
    scenario.h1("BURN - Tests Exhaustifs")
    
    admin = sp.test_account("admin")
    alice = sp.test_account("alice")
    bob = sp.test_account("bob")
    charlie = sp.test_account("charlie")
    
    c = main.NFTMarketplace(
        admin=admin.address,
        platform_fee_percent=sp.nat(5),
        mint_price=sp.tez(1),
        min_sale_price=sp.tez(1),
        max_metadata_length=sp.nat(256),
        max_supply=sp.nat(0)
    )
    scenario += c
    
    c.mint(metadata="ipfs://Qm1", royalty_percent=sp.nat(10),
           _sender=alice, _amount=sp.tez(1))
    c.mint(metadata="ipfs://Qm2", royalty_percent=sp.nat(5),
           _sender=bob, _amount=sp.tez(1))
    
    # Ajouter des offres sur token 0
    c.make_offer(token_id=sp.nat(0), duration_seconds=86400,
                 _sender=bob, _amount=sp.tez(50))
    c.make_offer(token_id=sp.nat(0), duration_seconds=86400,
                 _sender=charlie, _amount=sp.tez(60))
    
    # SUCCESS 1: Burn avec remboursement des offres
    scenario.h2("SUCCESS: Alice burn token 0 (offres remboursées)")
    c.burn(sp.nat(0), _sender=alice)
    scenario.verify(~c.data.tokens.contains(sp.nat(0)))
    scenario.verify(c.data.pending_payments[bob.address] == sp.tez(50))
    scenario.verify(c.data.pending_payments[charlie.address] == sp.tez(60))
    
    # SUCCESS 2: Burn simple
    scenario.h2("SUCCESS: Bob burn token 1")
    c.burn(sp.nat(1), _sender=bob)
    scenario.verify(~c.data.tokens.contains(sp.nat(1)))
    
    # FAIL 1: Pas propriétaire
    scenario.h2("FAIL: Pas propriétaire")
    c.mint(metadata="ipfs://Qm3", royalty_percent=sp.nat(5),
           _sender=alice, _amount=sp.tez(1))
    c.burn(sp.nat(2), _sender=bob,
           _valid=False, _exception="BURN: Not owner")
    
    # FAIL 2: Token listé
    scenario.h2("FAIL: Token listé")
    c.list_for_sale(token_id=sp.nat(2), price=sp.tez(10), _sender=alice)
    c.burn(sp.nat(2), _sender=alice,
           _valid=False, _exception="BURN: Token is listed")
    
    # FAIL 3: Token inexistant
    scenario.h2("FAIL: Token inexistant")
    c.burn(sp.nat(999), _sender=alice,
           _valid=False, _exception="BURN: Token not found")


# -------------------------------------------------------------------------------
# TEST 9: WITHDRAW (tous les cas)
# -------------------------------------------------------------------------------
@sp.add_test()
def test_withdraw_comprehensive():
    """Tests exhaustifs pour withdraw() et withdraw_fees()"""
    scenario = sp.test_scenario("Withdraw_Comprehensive", main)
    scenario.h1("WITHDRAW - Tests Exhaustifs")
    
    admin = sp.test_account("admin")
    alice = sp.test_account("alice")
    bob = sp.test_account("bob")
    
    c = main.NFTMarketplace(
        admin=admin.address,
        platform_fee_percent=sp.nat(5),
        mint_price=sp.tez(1),
        min_sale_price=sp.tez(1),
        max_metadata_length=sp.nat(256),
        max_supply=sp.nat(0)
    )
    scenario += c
    
    # Setup: créer des pending payments
    c.mint(metadata="ipfs://Qm1", royalty_percent=sp.nat(10),
           _sender=alice, _amount=sp.tez(1))
    c.list_for_sale(token_id=sp.nat(0), price=sp.tez(100), _sender=alice)
    c.buy(sp.nat(0), _sender=bob, _amount=sp.tez(100))
    
    # SUCCESS 1: Alice withdraw
    scenario.h2("SUCCESS: Alice withdraw ses gains")
    scenario.verify(c.data.pending_payments[alice.address] == sp.tez(95))
    c.withdraw(_sender=alice)
    scenario.verify(~c.data.pending_payments.contains(alice.address))
    
    # SUCCESS 2: Admin withdraw fees
    scenario.h2("SUCCESS: Admin withdraw fees")
    scenario.verify(c.data.collected_fees == sp.tez(6))  # 1 mint + 5 fee
    c.withdraw_fees(_sender=admin)
    scenario.verify(c.data.collected_fees == sp.mutez(0))
    
    # FAIL 1: Rien à withdraw
    scenario.h2("FAIL: Rien à withdraw")
    c.withdraw(_sender=alice,
               _valid=False, _exception="WITHDRAW: Nothing pending")
    
    # FAIL 2: Withdraw fees pas admin
    scenario.h2("FAIL: Withdraw fees - pas admin")
    c.mint(metadata="ipfs://Qm2", royalty_percent=sp.nat(5),
           _sender=alice, _amount=sp.tez(1))
    c.withdraw_fees(_sender=alice,
                    _valid=False, _exception="FEES: Not admin")
    
    # FAIL 3: Withdraw fees rien
    scenario.h2("FAIL: Withdraw fees - rien")
    c.withdraw_fees(_sender=admin)
    c.withdraw_fees(_sender=admin,
                    _valid=False, _exception="FEES: Nothing to withdraw")


# -------------------------------------------------------------------------------
# TEST 10: ADMIN (tous les cas)
# -------------------------------------------------------------------------------
@sp.add_test()
def test_admin_comprehensive():
    """Tests exhaustifs pour les fonctions admin"""
    scenario = sp.test_scenario("Admin_Comprehensive", main)
    scenario.h1("ADMIN - Tests Exhaustifs")
    
    admin = sp.test_account("admin")
    new_admin = sp.test_account("new_admin")
    alice = sp.test_account("alice")
    
    c = main.NFTMarketplace(
        admin=admin.address,
        platform_fee_percent=sp.nat(5),
        mint_price=sp.tez(1),
        min_sale_price=sp.tez(1),
        max_metadata_length=sp.nat(256),
        max_supply=sp.nat(0)
    )
    scenario += c
    
    # === PAUSE ===
    scenario.h2("PAUSE: Tests")
    
    # SUCCESS 1: Pause
    c.set_pause(True, _sender=admin)
    scenario.verify(c.data.paused == True)
    
    # SUCCESS 2: Unpause
    c.set_pause(False, _sender=admin)
    scenario.verify(c.data.paused == False)
    
    # FAIL 1: Pause pas admin
    c.set_pause(True, _sender=alice,
                _valid=False, _exception="PAUSE: Not admin")
    
    # === UPDATE FEES ===
    scenario.h2("UPDATE_FEE: Tests")
    
    # SUCCESS 1: Update fee
    c.update_platform_fee(sp.nat(10), _sender=admin)
    scenario.verify(c.data.platform_fee_percent == 10)
    
    # SUCCESS 2: Update fee to 0
    c.update_platform_fee(sp.nat(0), _sender=admin)
    scenario.verify(c.data.platform_fee_percent == 0)
    
    # FAIL 1: Fee > 20%
    c.update_platform_fee(sp.nat(21), _sender=admin,
                          _valid=False, _exception="FEE: Too high")
    
    # FAIL 2: Pas admin
    c.update_platform_fee(sp.nat(5), _sender=alice,
                          _valid=False, _exception="FEE: Not admin")
    
    # === UPDATE MINT PRICE ===
    scenario.h2("UPDATE_MINT_PRICE: Tests")
    
    # SUCCESS 1
    c.update_mint_price(sp.tez(2), _sender=admin)
    scenario.verify(c.data.mint_price == sp.tez(2))
    
    # SUCCESS 2: Prix à 0 (mint gratuit)
    c.update_mint_price(sp.mutez(0), _sender=admin)
    scenario.verify(c.data.mint_price == sp.mutez(0))
    
    # FAIL: Pas admin
    c.update_mint_price(sp.tez(5), _sender=alice,
                        _valid=False, _exception="PRICE: Not admin")
    
    # === CHANGE ADMIN ===
    scenario.h2("CHANGE_ADMIN: Tests")
    
    # SUCCESS 1: Propose admin
    c.propose_admin(new_admin.address, _sender=admin)
    scenario.verify(c.data.pending_admin == sp.Some(new_admin.address))
    
    # FAIL 1: Accept - pas le bon
    c.accept_admin(_sender=alice,
                   _valid=False, _exception="ADMIN: Not proposed admin")
    
    # SUCCESS 2: Cancel
    c.cancel_admin_change(_sender=admin)
    scenario.verify(c.data.pending_admin == None)
    
    # SUCCESS 3: Full change
    c.propose_admin(new_admin.address, _sender=admin)
    c.accept_admin(_sender=new_admin)
    scenario.verify(c.data.admin == new_admin.address)
    
    # FAIL 2: Old admin can't act
    c.set_pause(True, _sender=admin,
                _valid=False, _exception="PAUSE: Not admin")
    
    # SUCCESS 4: New admin can act
    c.set_pause(True, _sender=new_admin)
    scenario.verify(c.data.paused == True)


# -------------------------------------------------------------------------------
# TEST 11: ROYALTIES (cas spécial author != seller)
# -------------------------------------------------------------------------------
@sp.add_test()
def test_royalties_distribution():
    """Test distribution des royalties quand author != seller"""
    scenario = sp.test_scenario("Royalties_Distribution", main)
    scenario.h1("ROYALTIES - Distribution Correcte")
    
    admin = sp.test_account("admin")
    author = sp.test_account("author")
    seller = sp.test_account("seller")
    buyer = sp.test_account("buyer")
    
    c = main.NFTMarketplace(
        admin=admin.address,
        platform_fee_percent=sp.nat(5),
        mint_price=sp.tez(1),
        min_sale_price=sp.tez(1),
        max_metadata_length=sp.nat(256),
        max_supply=sp.nat(0)
    )
    scenario += c
    
    # Author crée le NFT
    c.mint(metadata="ipfs://Qm1", royalty_percent=sp.nat(10),
           _sender=author, _amount=sp.tez(1))
    
    # Author transfère à seller
    c.transfer(token_id=sp.nat(0), to_=seller.address, _sender=author)
    
    # Seller liste
    c.list_for_sale(token_id=sp.nat(0), price=sp.tez(100), _sender=seller)
    
    # Buyer achète
    scenario.h2("Achat: vérification distribution")
    c.buy(sp.nat(0), _sender=buyer, _amount=sp.tez(100))
    
    # Vérifications:
    # Prix: 100 tez
    # Royalty (10%): 10 tez -> author
    # Fee (5%): 5 tez -> platform
    # Seller: 85 tez
    
    scenario.verify(c.data.pending_payments[author.address] == sp.tez(10))
    scenario.verify(c.data.pending_payments[seller.address] == sp.tez(85))
    scenario.verify(c.data.collected_fees == sp.tez(6))  # 1 mint + 5 fee
    
    # Buyer revend (author reçoit encore les royalties)
    scenario.h2("Revente: author reçoit encore royalties")
    c.list_for_sale(token_id=sp.nat(0), price=sp.tez(200), _sender=buyer)
    
    # Nouveau buyer
    new_buyer = sp.test_account("new_buyer")
    c.buy(sp.nat(0), _sender=new_buyer, _amount=sp.tez(200))
    
    # Nouvelles royalties: 200 * 10% = 20 tez à author
    # Total author: 10 + 20 = 30 tez
    scenario.verify(c.data.pending_payments[author.address] == sp.tez(30))


# -------------------------------------------------------------------------------
# TEST 12: VIEWS (tous les cas)
# -------------------------------------------------------------------------------
@sp.add_test()
def test_views_comprehensive():
    """Tests exhaustifs pour les vues onchain"""
    scenario = sp.test_scenario("Views_Comprehensive", main)
    scenario.h1("VIEWS - Tests Exhaustifs")
    
    admin = sp.test_account("admin")
    alice = sp.test_account("alice")
    bob = sp.test_account("bob")
    
    c = main.NFTMarketplace(
        admin=admin.address,
        platform_fee_percent=sp.nat(5),
        mint_price=sp.tez(1),
        min_sale_price=sp.tez(2),
        max_metadata_length=sp.nat(256),
        max_supply=sp.nat(100)
    )
    scenario += c
    
    # Mint
    c.mint(metadata="ipfs://Qm1", royalty_percent=sp.nat(10),
           _sender=alice, _amount=sp.tez(1))
    
    # Test get_total_supply
    scenario.h2("VIEW: get_total_supply")
    scenario.verify(c.get_total_supply() == 1)
    
    # Test get_owner
    scenario.h2("VIEW: get_owner")
    scenario.verify(c.get_owner(sp.nat(0)) == alice.address)
    
    # Test is_for_sale (non listé)
    scenario.h2("VIEW: is_for_sale (non listé)")
    scenario.verify(c.is_for_sale(sp.nat(0)) == False)
    
    # Test get_price (non listé)
    scenario.h2("VIEW: get_price (non listé)")
    scenario.verify(c.get_price(sp.nat(0)) == sp.mutez(0))
    
    # List
    c.list_for_sale(token_id=sp.nat(0), price=sp.tez(50), _sender=alice)
    
    # Test is_for_sale (listé)
    scenario.h2("VIEW: is_for_sale (listé)")
    scenario.verify(c.is_for_sale(sp.nat(0)) == True)
    
    # Test get_price (listé)
    scenario.h2("VIEW: get_price (listé)")
    scenario.verify(c.get_price(sp.nat(0)) == sp.tez(50))
    
    # Test get_admin
    scenario.h2("VIEW: get_admin")
    scenario.verify(c.get_admin() == admin.address)
    
    # Test is_paused
    scenario.h2("VIEW: is_paused")
    scenario.verify(c.is_paused() == False)
    c.set_pause(True, _sender=admin)
    scenario.verify(c.is_paused() == True)
    c.set_pause(False, _sender=admin)
    
    # Test get_pending
    scenario.h2("VIEW: get_pending")
    scenario.verify(c.get_pending(alice.address) == sp.mutez(0))
    c.buy(sp.nat(0), _sender=bob, _amount=sp.tez(50))
    scenario.verify(c.get_pending(alice.address) > sp.mutez(0))
    
    # Test get_config
    scenario.h2("VIEW: get_config")
    config = c.get_config()
    scenario.verify(config.platform_fee == 5)
    scenario.verify(config.mint_price == sp.tez(1))
    scenario.verify(config.min_sale_price == sp.tez(2))
    scenario.verify(config.max_supply == 100)
    
    # Test get_token
    scenario.h2("VIEW: get_token")
    c.mint(metadata="ipfs://Qm2", royalty_percent=sp.nat(5),
           _sender=bob, _amount=sp.tez(1))
    token = c.get_token(sp.nat(1))
    scenario.verify(token.owner == bob.address)
    scenario.verify(token.author == bob.address)
    scenario.verify(token.royalty_percent == 5)


# -------------------------------------------------------------------------------
# TEST 13: EDGE CASES
# -------------------------------------------------------------------------------
@sp.add_test()
def test_edge_cases():
    """Tests des cas limites"""
    scenario = sp.test_scenario("Edge_Cases", main)
    scenario.h1("EDGE CASES")
    
    admin = sp.test_account("admin")
    alice = sp.test_account("alice")
    bob = sp.test_account("bob")
    
    c = main.NFTMarketplace(
        admin=admin.address,
        platform_fee_percent=sp.nat(0),  # 0% fees
        mint_price=sp.mutez(0),  # Mint gratuit
        min_sale_price=sp.mutez(1),  # Prix minimum très bas
        max_metadata_length=sp.nat(10),  # Très court
        max_supply=sp.nat(2)  # Très limité
    )
    scenario += c
    
    # Edge 1: Mint gratuit
    scenario.h2("EDGE: Mint gratuit")
    c.mint(metadata="short", royalty_percent=sp.nat(0),
           _sender=alice, _amount=sp.mutez(0))
    scenario.verify(c.data.next_id == 1)
    
    # Edge 2: 0% royalties et 0% fees
    scenario.h2("EDGE: 0% royalties, 0% fees")
    c.list_for_sale(token_id=sp.nat(0), price=sp.mutez(1000), _sender=alice)
    c.buy(sp.nat(0), _sender=bob, _amount=sp.mutez(1000))
    # Alice reçoit tout (1000 mutez)
    scenario.verify(c.data.pending_payments[alice.address] == sp.mutez(1000))
    scenario.verify(c.data.collected_fees == sp.mutez(0))
    
    # Edge 3: Supply max
    scenario.h2("EDGE: Atteindre supply max")
    c.mint(metadata="short2", royalty_percent=sp.nat(50),
           _sender=bob, _amount=sp.mutez(0))
    c.mint(metadata="short3", royalty_percent=sp.nat(0),
           _sender=alice, _amount=sp.mutez(0),
           _valid=False, _exception="MINT: Max supply reached")
    
    # Edge 4: Prix minimum = 1 mutez
    scenario.h2("EDGE: Prix minimum 1 mutez")
    c.list_for_sale(token_id=sp.nat(1), price=sp.mutez(1), _sender=bob)
    scenario.verify(c.data.tokens[1].price == sp.mutez(1))
